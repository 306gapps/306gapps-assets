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


def unpack_payload(ota: Path, work: Path, partitions=PARTITIONS) -> dict[str, Path]:
    """Pull payload.bin out of the OTA and split it into partition images."""
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

    out = work / "images"
    out.mkdir(exist_ok=True)
    dumper = need("payload-dumper-go",
                  "install from https://github.com/ssut/payload-dumper-go")
    print(f"  splitting payload into {', '.join(partitions)}")
    run([dumper, "-o", str(out), "-p", ",".join(partitions), str(payload)])

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


def image_format(img: Path) -> str:
    with open(img, "rb") as f:
        f.seek(1024)
        head = f.read(64)
    if len(head) >= 4 and struct.unpack("<I", head[:4])[0] == EROFS_MAGIC:
        return "erofs"
    if len(head) >= 58 and struct.unpack("<H", head[56:58])[0] == EXT4_MAGIC:
        return "ext4"
    return "unknown"


def extract_image(img: Path, dest: Path) -> None:
    """Unpack a partition image into dest, preserving modes and xattrs."""
    dest.mkdir(parents=True, exist_ok=True)
    fmt = image_format(img)
    print(f"  {img.name}: {fmt}")

    if fmt == "erofs":
        tool = need("fsck.erofs", "install erofs-utils")
        run([tool, f"--extract={dest}", "--xattrs", "--overwrite", str(img)])
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
    """Some dumps nest the partition under itself (product/product/...).

    Collapse that so paths match what the manifest expects.
    """
    for part in PARTITIONS:
        base = tree / part
        nested = base / part
        if nested.is_dir() and not (base / "etc").exists():
            print(f"  flattening {part}/{part}")
            for child in nested.iterdir():
                shutil.move(str(child), str(base / child.name))
            nested.rmdir()


def check_tools() -> int:
    """Report which external tools are present, for CI preflight."""
    wanted = [
        ("payload-dumper-go", "split payload.bin into partition images"),
        ("fsck.erofs", "extract EROFS partitions (Android 13+)"),
        ("debugfs", "extract ext4 partitions (older ROMs)"),
    ]
    missing = 0
    for tool, why in wanted:
        path = shutil.which(tool)
        print(f"{'ok  ' if path else 'MISS'}  {tool:20s} {path or why}")
        missing += path is None
    return 1 if missing else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", help="OTA zip URL")
    p.add_argument("--ota", help="local OTA zip (skips the download)")
    p.add_argument("--sha256", default="", help="expected OTA digest")
    p.add_argument("--work", default="work", help="scratch directory")
    p.add_argument("--tree", default="work/tree", help="where to write the tree")
    p.add_argument("--partitions", default=",".join(PARTITIONS))
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
        images = unpack_payload(ota, work, parts)

        if tree.exists():
            shutil.rmtree(tree)
        for part, img in images.items():
            extract_image(img, tree / part)
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
