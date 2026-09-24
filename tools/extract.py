#!/usr/bin/env python3
"""Turn a Pixel OTA zip into an extracted partition tree.

    OTA zip -> payload.bin -> {product,system,system_ext}.img -> tree/<partition>/

Partition images are EROFS on recent Pixels and ext4 on older ones; both are
unpacked without root or loopback mounts.
"""

import argparse
import hashlib
import os
import shutil
import struct
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PARTITIONS = ("system", "system_ext", "product")

EROFS_MAGIC = 0xE0F5E1E2   # at offset 1024
EXT4_MAGIC = 0xEF53        # at offset 1080


class MissingTool(Exception):
    pass


# erofs-utils before 1.8 silently truncates large files during extraction and
# still exits zero. That produced a 148 MiB apex short by 24 KiB, which passed
# every check the dump made and would have shipped.
MIN_EROFS = (1, 8)


def erofs_version(tool: str) -> tuple[int, ...] | None:
    """Parse the version fsck.erofs reports, or None if it cannot be read."""
    try:
        out = subprocess.run([tool, "-V"], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"erofs-utils\)?\s+([0-9]+(?:\.[0-9]+)*)", out)
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def check_erofs(tool: str) -> None:
    """Refuse to extract with a version known to corrupt output."""
    v = erofs_version(tool)
    if v is None:
        print("warning: could not determine the erofs-utils version; "
              f"{MIN_EROFS[0]}.{MIN_EROFS[1]} or newer is required",
              file=sys.stderr)
        return
    if v < MIN_EROFS:
        raise SystemExit(
            f"error: erofs-utils {'.'.join(map(str, v))} truncates large files "
            f"during extraction and reports success.\n"
            f"Install {MIN_EROFS[0]}.{MIN_EROFS[1]} or newer -- Ubuntu ships "
            f"1.7.1, which is affected."
        )


def need(tool: str, hint: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise MissingTool(f"{tool} not found - {hint}")
    return path


def run(cmd: list[str], **kw) -> None:
    subprocess.run(cmd, check=True, **kw)


def download(url: str, dest: Path, expect_sha256: str = "") -> Path:
    """Fetch url to dest, verifying the digest Google publishes."""
    if dest.exists() and expect_sha256 and sha256_of(dest) == expect_sha256:
        print(f"  reusing {dest.name}")
        return dest

    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={
        "Cookie": "devsite_wall_acks=nexus-ota-tos",
        "User-Agent": "306gapps-assets",
    })
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 22):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done * 100 // total}% "
                      f"({done >> 20}/{total >> 20} MiB)", end="", flush=True)
    print()

    got = h.hexdigest()
    if expect_sha256 and got != expect_sha256:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch: expected {expect_sha256}, got {got}")
    tmp.replace(dest)
    return dest


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def unpack_payload(ota: Path, work: Path, partitions=PARTITIONS,
                   reclaim: bool = False) -> dict[str, Path]:
    """Pull payload.bin out of the OTA and split it into partition images.

    With reclaim set, each intermediate is deleted as soon as it has been
    consumed. The OTA, the payload and the images are each several gigabytes
    and CI runners do not have room for all of them at once.
    """
    payload = work / "payload.bin"
    if not payload.exists():
        with zipfile.ZipFile(ota) as z:
            names = [n for n in z.namelist() if n.endswith("payload.bin")]
            if not names:
                raise SystemExit(f"{ota} contains no payload.bin "
                                 "(is it a factory image rather than an OTA?)")
            print(f"  extracting {names[0]}")
            with z.open(names[0]) as src, open(payload, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 22)
        if reclaim:
            # The payload is out; the zip around it is dead weight from here.
            drop(ota)

    out = work / "images"
    out.mkdir(exist_ok=True)

    # Splitting a 4 GB payload takes minutes; skip it when every image we need
    # is already sitting there from a previous run.
    missing = [p for p in partitions if not (out / f"{p}.img").exists()]
    if missing:
        dumper = need("payload-dumper-go",
                      "install from https://github.com/ssut/payload-dumper-go")
        print(f"  splitting payload into {', '.join(missing)}")
        run([dumper, "-o", str(out), "-p", ",".join(missing), str(payload)])
        if reclaim:
            # The images are split; nothing reads the payload again.
            drop(payload)
    else:
        print(f"  reusing images already split from the payload")

    images = {}
    for part in partitions:
        img = out / f"{part}.img"
        if img.exists():
            images[part] = img
        else:
            print(f"  warning: {part}.img not produced", file=sys.stderr)
    if not images:
        raise SystemExit("payload contained none of the requested partitions")
    return images


def drop(path: Path) -> None:
    """Delete a large intermediate and say how much room it returned."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    try:
        path.unlink()
    except OSError:
        return
    print(f"  reclaimed {size / (1 << 30):.1f} GiB from {path.name}")


def image_format(img: Path) -> str:
    with open(img, "rb") as f:
        f.seek(1024)
        head = f.read(64)
    if len(head) >= 4 and struct.unpack("<I", head[:4])[0] == EROFS_MAGIC:
        return "erofs"
    if len(head) >= 58 and struct.unpack("<H", head[56:58])[0] == EXT4_MAGIC:
        return "ext4"
    return "unknown"


def extract_image(img: Path, dest: Path, xattrs: bool = False) -> None:
    """Unpack a partition image into dest, preserving modes.

    SELinux labels are not captured. Writing a security.selinux xattr needs
    CAP_SYS_ADMIN, so an unprivileged extraction -- which is what CI does --
    fails outright with --xattrs. The labels are not missed: every path a gapps
    package installs to falls under the generic file_contexts rules that
    resolve to system_file, which is exactly what the installer applies by
    default per partition. Pass --xattrs when extracting as root if you want
    them recorded anyway.
    """
    dest.mkdir(parents=True, exist_ok=True)
    fmt = image_format(img)
    print(f"  {img.name}: {fmt}")

    if fmt == "erofs":
        tool = need("fsck.erofs", "install erofs-utils")
        check_erofs(tool)
        # --preserve-perms matters: run as an ordinary user, fsck.erofs applies
        # the umask to extracted files, which would record the wrong modes in
        # the manifest.
        cmd = [tool, f"--extract={dest}", "--preserve-perms", "--overwrite"]
        if xattrs:
            cmd.append("--xattrs")
        run(cmd + [str(img)])
    elif fmt == "ext4":
        tool = need("debugfs", "install e2fsprogs")
        run([tool, "-R", f"rdump / {dest}", str(img)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise SystemExit(
            f"{img.name}: unrecognised filesystem. Recent Pixels use EROFS and "
            "older ones ext4; anything else needs a new extractor here."
        )


def flatten(tree: Path) -> None:
    """Reduce a system-as-root image to just the partition's own content.

    system.img on modern devices is extracted at the *device* root: alongside
    the real /system content (in a nested system/ directory) sit mount points
    like dev/, proc/ and mnt/ that belong to no partition. product.img and
    system_ext.img have no such wrapper and are left alone.

    The nested directory replaces the base rather than merging into it -- the
    two overlap (both carry bin/, etc/) and merging silently mixes mount points
    into the partition.
    """
    for part in PARTITIONS:
        base = tree / part
        nested = base / part
        if not nested.is_dir():
            continue
        print(f"  {part}: keeping {part}/{part} (system-as-root layout)")
        staging = tree / f".{part}.flatten"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.move(str(nested), str(staging))
        shutil.rmtree(base)
        shutil.move(str(staging), str(base))


def check_tools() -> int:
    """Report which external tools are present, for CI preflight."""
    wanted = [
        ("payload-dumper-go", "split payload.bin into partition images"),
        ("fsck.erofs", "extract EROFS partitions (Android 13+)"),
        ("debugfs", "extract ext4 partitions (older ROMs)"),
    ]
    problems = 0
    for tool, why in wanted:
        path = shutil.which(tool)
        note = path or why
        if path and tool == "fsck.erofs":
            v = erofs_version(path)
            shown = ".".join(map(str, v)) if v else "unknown"
            if v and v < MIN_EROFS:
                print(f"BAD   {tool:20s} {path} (version {shown} corrupts "
                      f"large files; need {MIN_EROFS[0]}.{MIN_EROFS[1]}+)")
                problems += 1
                continue
            note = f"{path} (version {shown})"
        print(f"{'ok  ' if path else 'MISS'}  {tool:20s} {note}")
        problems += path is None
    return 1 if problems else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", help="OTA zip URL")
    p.add_argument("--ota", help="local OTA zip (skips the download)")
    p.add_argument("--sha256", default="", help="expected OTA digest")
    p.add_argument("--work", default="work", help="scratch directory")
    p.add_argument("--tree", default="work/tree", help="where to write the tree")
    p.add_argument("--partitions", default=",".join(PARTITIONS))
    p.add_argument("--xattrs", action="store_true",
                   help="record SELinux labels (requires running as root)")
    p.add_argument("--reclaim", action="store_true",
                   help="delete each intermediate as soon as it is consumed "
                        "(halves the peak disk a dump needs)")
    p.add_argument("--check-tools", action="store_true")
    args = p.parse_args()

    if args.check_tools:
        return check_tools()
    if not args.url and not args.ota:
        p.error("one of --url or --ota is required")

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    tree = Path(args.tree)

    try:
        if args.ota:
            ota = Path(args.ota)
        else:
            ota = download(args.url, work / "ota.zip", args.sha256)

        parts = tuple(x.strip() for x in args.partitions.split(",") if x.strip())
        # Only reclaim an OTA we downloaded ourselves; one the caller supplied
        # is theirs to keep.
        images = unpack_payload(ota, work, parts,
                                reclaim=args.reclaim and not args.ota)

        if tree.exists():
            shutil.rmtree(tree)
        # Largest first: extracting product before system means the biggest
        # image is freed earliest, which is when headroom is tightest.
        order = sorted(images, key=lambda p: images[p].stat().st_size, reverse=True)
        for part in order:
            extract_image(images[part], tree / part, args.xattrs)
            if args.reclaim:
                drop(images[part])
        flatten(tree)
    except MissingTool as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"error: {e.cmd[0]} failed with status {e.returncode}", file=sys.stderr)
        return 1

    count = sum(len(f) for _, _, f in os.walk(tree))
    print(f"{tree}: {count} files across {', '.join(sorted(images))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
