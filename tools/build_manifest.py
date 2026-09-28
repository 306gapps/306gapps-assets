#!/usr/bin/env python3
"""Turn a dumped partition tree into a release manifest plus an asset bundle.

Walks the extracted partitions, assigns every file to exactly one package by
glob, and reports anything left unclaimed -- which is how a newly added Google
app surfaces instead of silently going missing.
"""

import argparse
import hashlib
import json
import os
import re
import gzip
import io
import shutil
import struct
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from axml import MalformedAXML, package_name
from globmatch import matches

SCHEMA = 1
PARTITIONS = ("system", "system_ext", "product", "vendor")

# Files that are part of the ROM rather than of any Google app.
IGNORE = (
    "**/lost+found/**",
    "**/*.prop",
    "**/etc/selinux/**",
    "**/etc/fs_config_*",

    # Every compilation artifact. An odex records the checksums of the boot
    # classpath it was compiled against, and every custom ROM has a different
    # one, so ART rejects it and compiles the apk itself regardless. A profile
    # would survive the move, but its only benefit is compiling hot methods
    # sooner, and a slow first boot is expected after flashing anyway.
    #
    # None of these change what is installed, only how quickly it warms up, and
    # ART regenerates whatever it wants. For the ota target they are worse than
    # useless: the ROM build runs its own dexpreopt.
    "**/oat/**",
    "**/*.odex",
    "**/*.vdex",
    "**/*.art",
    "**/*.dex",
    "**/*.prof",
)

KIND_BY_PATH = (
    ("**/etc/permissions/**", "permission"),
    ("**/etc/sysconfig/**", "sysconfig"),
    ("**/etc/default-permissions/**", "sysconfig"),
    ("**/overlay/**", "overlay"),
    ("**/framework/**", "framework"),
    ("**/lib/**", "lib"),
    ("**/lib64/**", "lib"),
    ("**/*.apk", "apk"),
    ("**/*.jar", "jar"),
    ("**/etc/**", "etc"),
)


# Every one of these is a zip underneath, so a truncated or mangled extraction
# shows up as an unreadable archive.
ZIP_KINDS = (".apk", ".apex", ".capex", ".jar")


def verify_container(path: Path) -> str:
    """Return an error string if a zip-shaped payload is not readable.

    An extractor that silently truncates a file and exits zero is not
    hypothetical: erofs-utils 1.7.1 cut 24 KiB off a 148 MiB apex and reported
    success, which would have shipped a package that cannot install. Reading
    the central directory is cheap and catches exactly that.

    Chrome, the WebView and the Trichrome library ship gzipped -- Android
    inflates compressed system apps on first boot -- and they are among the
    largest payloads here, so they are unpacked and checked too rather than
    skipped for want of a matching suffix.
    """
    name = str(path)
    opener = open
    if name.endswith(".gz"):
        inner = name[:-3]
        if not inner.endswith(ZIP_KINDS):
            return ""
        opener = gzip.open
    elif not name.endswith(ZIP_KINDS):
        return ""

    try:
        with opener(path, "rb") as fh:
            with zipfile.ZipFile(fh) as z:
                if not z.namelist():
                    return "archive is empty"
    except zipfile.BadZipFile as e:
        return f"not a readable archive ({e})"
    except (OSError, EOFError) as e:
        return f"cannot read ({e})"
    return ""


def carried_entries(defs_dir: Path, d: dict, assets: Path) -> list[dict]:
    """Build file records for payloads that do not come from the dump.

    Everything else in a release is extracted from the image named in the
    manifest and refreshed whenever that device gets a new build. A carried
    file is not: Google no longer ships it, so there is no image to take it
    from. Marking it says plainly which payloads cannot be refreshed.
    """
    out = []
    for item in d.get("carry", []):
        src = defs_dir / item["file"]
        if not src.is_file():
            raise SystemExit(f"error: {d['id']} carries {item['file']}, "
                             f"which is not at {src}")
        if problem := verify_container(src):
            raise SystemExit(f"error: {d['id']} carries {item['file']}: {problem}")
        digest, size = sha256_of(src)
        name = asset_name(digest, item["path"])
        dest = assets / name
        if not dest.exists():
            shutil.copy2(src, dest)
        out.append({
            "path": item["path"],
            "asset": name,
            "sha256": digest,
            "size": size,
            "mode": item.get("mode", "0644"),
            "kind": classify(item["path"]),
            "carried": True,
        })
    return out


def read_package_id(root: Path, rel: str) -> str:
    """Read the Android package id from an apk, inflating it if gzipped."""
    full = root / rel
    try:
        if rel.endswith(".gz"):
            data = gzip.open(full, "rb").read()
            z = zipfile.ZipFile(io.BytesIO(data))
        else:
            z = zipfile.ZipFile(full)
        with z:
            return package_name(z.read("AndroidManifest.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, MalformedAXML, struct.error):
        return ""


def package_ids(root: Path, entries: list[dict], declared) -> list[str]:
    """The Android package ids a package installs, for clearing app data.

    Usually one, read from the principal apk: the shallowest path wins, since a
    chimera submodule sits deeper than the apk that owns it and shares its data
    directory. Declared ids win outright, which is how a package names several
    -- the sync adapters are two apps in one selection -- and how anything
    auto-detection cannot see is covered, whether it is inside an apex or
    carried rather than dumped.
    """
    if declared:
        return [declared] if isinstance(declared, str) else list(declared)
    apks = [e for e in entries if e["path"].endswith((".apk", ".apk.gz"))]
    if not apks:
        return []
    apks.sort(key=lambda e: (e["path"].count("/"), -e.get("size", 0)))
    pid = read_package_id(root, apks[0]["path"])
    return [pid] if pid else []


def main_package_id(root: Path, entries: list[dict]) -> str:
    """Pick the package id of a package's principal apk.

    Shallowest path wins, then largest: a chimera submodule sits deeper than
    the apk that owns it, and picking one of those would clean the wrong data
    directory. Where even that is ambiguous -- GMS Core on Android 17 keeps its
    real apk inside an apex -- the definition declares the id instead.
    """
    apks = [e for e in entries if e["path"].endswith((".apk", ".apk.gz"))]
    if not apks:
        return ""
    apks.sort(key=lambda e: (e["path"].count("/"), -e.get("size", 0)))
    return read_package_id(root, apks[0]["path"])


def classify(path: str) -> str:
    for pattern, kind in KIND_BY_PATH:
        if matches(pattern, path):
            return kind
    return "etc"


def selinux_context(full: Path) -> str:
    """Read the SELinux label the dump preserved, if any."""
    try:
        return os.getxattr(full, "security.selinux").decode().rstrip("\x00")
    except (OSError, AttributeError):
        return ""


def sha256_of(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def walk_tree(root: Path) -> list[str]:
    """Return every regular file and symlink under root, partition-relative.

    Symlinks are included rather than skipped: apps whose native libraries are
    linked in from elsewhere on the partition break silently without them.
    """
    out = []
    for part in PARTITIONS:
        base = root / part
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            # A symlink to a directory shows up in dirnames, not filenames.
            for name in list(dirnames):
                full = Path(dirpath) / name
                if full.is_symlink():
                    dirnames.remove(name)
                    out.append(str(full.relative_to(root)))
            for name in filenames:
                full = Path(dirpath) / name
                if full.is_symlink() or full.is_file():
                    out.append(str(full.relative_to(root)))
    return sorted(out)


def read_prop(root: Path, key: str) -> str:
    """Look a build property up across the partitions that carry one."""
    for candidate in (
        root / "system/build.prop",
        root / "product/build.prop",
        root / "product/etc/build.prop",
        root / "system_ext/etc/build.prop",
    ):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(errors="replace").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


class Conflict(Exception):
    pass


def assign(files: list[str], defs: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    """Map each file to at most one package.

    Raises Conflict when two packages claim the same file, because the builder
    refuses such a manifest and the ambiguity should be fixed in the defs.
    """
    claimed: dict[str, str] = {}
    by_package: dict[str, list[str]] = {d["id"]: [] for d in defs}

    for path in files:
        if any(matches(p, path) for p in IGNORE):
            continue
        for d in defs:
            if not any(matches(p, path) for p in d.get("include", [])):
                continue
            if path in claimed:
                raise Conflict(
                    f"{path} is claimed by both {claimed[path]} and {d['id']}"
                )
            claimed[path] = d["id"]
            by_package[d["id"]].append(path)

    unclaimed = [f for f in files if f not in claimed
                 and not any(matches(p, f) for p in IGNORE)]
    return by_package, unclaimed


# <library name="..." file="/system/framework/foo.jar"/> in a permissions xml
# declares a shared library an app links against at runtime.
LIBRARY_REF = re.compile(r'file="(/[^"]+\.jar)"')


def check_declared_libraries(root: Path, packages: list[dict]) -> list[str]:
    """Warn when a claimed permissions xml declares a jar no package ships.

    An app whose permissions file names a shared library that is not installed
    fails to start, and nothing else in the pipeline would notice: the xml is
    present, the apk is present, and only the jar between them is missing.
    """
    provided = {f["path"] for p in packages for f in p["files"]}
    problems = []
    for p in packages:
        for f in p["files"]:
            if not f["path"].endswith(".xml") or "/etc/permissions/" not in f["path"]:
                continue
            full = root / f["path"]
            try:
                text = full.read_text(errors="replace")
            except OSError:
                continue
            for ref in LIBRARY_REF.findall(text):
                want = ref.lstrip("/")
                if want in provided:
                    continue
                # A jar the ROM itself provides is not ours to ship.
                if (root / want).exists():
                    problems.append(
                        f"{p['id']}: {f['path']} declares {ref}, which is in "
                        f"the dump but no package claims"
                    )
    return problems


def check_symlink_targets(packages: list[dict]) -> list[str]:
    """Warn when a package ships a link whose target it does not also ship.

    Apps whose native libraries live in the partition's lib64 are linked in
    rather than copied. Claiming the app without its libraries produces a
    dangling link and an app that will not start.
    """
    provided = {f["path"] for p in packages for f in p["files"]}
    problems = []
    for p in packages:
        for f in p["files"]:
            if f.get("kind") != "symlink":
                continue
            target = f["target"]
            if not target.startswith("/"):
                # Relative targets resolve next to the link and are normally
                # within the same directory tree we already ship.
                continue
            claimed = target.lstrip("/")
            if claimed not in provided:
                problems.append(
                    f"{p['id']}: {f['path']} links to {target}, which no "
                    f"package ships -- the link will dangle"
                )
    return problems


def check_references(packages: list[dict]) -> list[str]:
    """Verify requires/conflicts still resolve.

    A package that matched no files is dropped from the manifest, which can
    leave a dangling reference behind -- the builder rejects that, so catch it
    here where the fix is obvious.
    """
    present = {p["id"] for p in packages}
    problems = []
    for p in packages:
        for key in ("requires", "conflicts"):
            for ref in p.get(key, []):
                if ref not in present:
                    problems.append(
                        f"{p['id']} {key} {ref!r}, which is not in this release "
                        f"(missing from the defs, or it matched no files)"
                    )
    return problems


# Payload kinds worth reporting when nothing claims them. Restricting this to
# .apk once hid a 148 MiB GMS Core apex, which ships as an apex rather than an
# apk on Android 17 -- the report has to cover every kind of code container.
NOTABLE = (".apk", ".apex", ".capex", ".jar")

# Directories that hold installable code, as opposed to data or resources.
CODE_DIRS = ("app", "priv-app", "apex", "framework")


def interesting(path: str) -> bool:
    """Report unclaimed code that Google added, not the AOSP base.

    /system is the stock platform and is full of unclaimed jars that are
    nothing to do with gapps; drowning the report in those is how a real
    omission gets missed.
    """
    if not path.endswith(NOTABLE):
        return False
    if path.startswith("system/"):
        return False
    return any(f"/{d}/" in f"/{path}" for d in CODE_DIRS)


def asset_name(digest: str, path: str) -> str:
    """Content-addressed but still readable in a release's asset list."""
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(path))
    return f"{digest[:16]}-{base}"


def build(args) -> int:
    root = Path(args.tree)
    defs_doc = yaml.safe_load(Path(args.packages).read_text())
    defs = defs_doc["packages"]
    android = defs_doc["android"]

    files = walk_tree(root)
    if not files:
        print(f"error: no partition directories found under {root}", file=sys.stderr)
        return 1

    excluded = defs_doc.get("exclude", [])
    try:
        by_package, unclaimed = assign(files, defs)
    except Conflict as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    substitutions = {
        "gms_version": read_prop(root, "ro.com.google.gmsversion"),
        "build": args.build,
        "device": args.device,
    }

    assets = Path(args.assets)
    assets.mkdir(parents=True, exist_ok=True)

    packages = []
    empty = []
    no_package: list[str] = []
    corrupt: list[str] = []
    for d in defs:
        entries = []
        for rel in by_package[d["id"]]:
            full = root / rel

            # A symlink is recorded by its target; there is no payload to copy
            # and nothing to hash.
            if full.is_symlink():
                entries.append({
                    "path": rel,
                    "size": 0,
                    "mode": "0777",
                    "kind": "symlink",
                    "target": os.readlink(full),
                })
                continue

            mode = f"{full.stat().st_mode & 0o7777:04o}"

            # A zero-length file carries no payload. There is nothing to store,
            # and GitHub rejects a zero-length release asset outright
            # ("HTTP 400: Bad Content-Length"), so publishing one is not an
            # option even if we wanted to. The builders recreate it empty.
            if full.stat().st_size == 0:
                entries.append({
                    "path": rel, "size": 0, "mode": mode,
                    "context": selinux_context(full), "kind": classify(rel),
                })
                continue

            if problem := verify_container(full):
                corrupt.append(f"{rel}: {problem}")
                continue

            digest, size = sha256_of(full)
            name = asset_name(digest, rel)
            dest = assets / name
            if not dest.exists():
                shutil.copy2(full, dest)
            entries.append({
                "path": rel,
                "asset": name,
                "sha256": digest,
                "size": size,
                "mode": mode,
                "context": selinux_context(full),
                "kind": classify(rel),
            })

        entries.extend(carried_entries(Path(args.packages).parent.parent, d, assets))

        if not entries:
            empty.append(d["id"])
            continue

        pkg = {
            "id": d["id"],
            "name": d["name"],
            "category": d.get("category", "extras"),
            "files": sorted(entries, key=lambda e: e["path"]),
        }

        # The Android package ids, so an uninstall can clear app data.
        # Declared ones win: auto-detection cannot see inside an apex.
        ids = package_ids(root, entries, d.get("package"))
        if ids:
            pkg["packages"] = ids
        else:
            no_package.append(d["id"])
        for key in ("summary", "required", "default"):
            if d.get(key):
                pkg[key] = d[key]
        for key in ("requires", "conflicts", "removes"):
            if d.get(key):
                pkg[key] = d[key]
        if d.get("props"):
            pkg["props"] = {
                k: v.format(**substitutions) if isinstance(v, str) else v
                for k, v in d["props"].items()
            }
        packages.append(pkg)

    if corrupt:
        print(f"\nerror: {len(corrupt)} payload(s) did not survive extraction:",
              file=sys.stderr)
        for line in corrupt:
            print(f"  {line}", file=sys.stderr)
        print("\nThis is an extraction bug, not a packaging one. Check the "
              "erofs-utils version:\nolder releases truncate large files and "
              "still exit zero.", file=sys.stderr)
        return 1

    if problems := check_references(packages):
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        return 1

    for line in check_symlink_targets(packages):
        print(f"warning: {line}", file=sys.stderr)

    for line in check_declared_libraries(root, packages):
        print(f"warning: {line}", file=sys.stderr)

    release_id = args.release or f"a{android['version']}-{args.build.lower()}"
    manifest = {
        "schema": SCHEMA,
        "release": {
            "id": release_id,
            "android": {
                "api": android["api"],
                "version": str(android["version"]),
                "codename": android.get("codename", ""),
            },
            "source": {
                "device": args.device,
                "build": args.build,
                "image": args.image_url,
                "sha256": args.image_sha256,
            },
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "asset_base": args.asset_base,
        },
        "packages": packages,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")

    total = sum(f["size"] for p in packages for f in p["files"])
    print(f"{out}: {len(packages)} packages, {len(files)} files seen, "
          f"{total / 1024 / 1024:.1f} MiB claimed")

    if empty:
        print(f"warning: {len(empty)} package(s) matched no files: "
              f"{', '.join(empty)}", file=sys.stderr)

    if no_package:
        print(f"warning: {len(no_package)} package(s) have no Android package id, "
              f"so an uninstall cannot clear their data: "
              f"{', '.join(no_package)}", file=sys.stderr)

    if excluded:
        before = len(unclaimed)
        unclaimed = [f for f in unclaimed
                     if not any(f"/{name}/" in f"/{f}" for name in excluded)]
        print(f"  {before - len(unclaimed)} file(s) excluded by choice: "
              f"{', '.join(excluded)}")

    notable = [f for f in unclaimed if interesting(f)]
    if notable:
        print(f"\nwarning: {len(notable)} unclaimed file(s) on "
              f"{'/'.join(sorted({f.split('/')[0] for f in notable}))} -- "
              f"add them to {args.packages} or ignore them:", file=sys.stderr)
        for f in notable:
            print(f"  {f}", file=sys.stderr)

    if args.report:
        Path(args.report).write_text("\n".join(unclaimed) + "\n")

    if args.strict and (notable or empty):
        print("\nerror: --strict and the dump was not fully accounted for",
              file=sys.stderr)
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tree", required=True, help="extracted partition tree")
    p.add_argument("--packages", required=True, help="package definition yaml")
    p.add_argument("--assets", required=True, help="directory to collect payloads into")
    p.add_argument("--out", required=True, help="manifest.json to write")
    p.add_argument("--device", required=True)
    p.add_argument("--build", required=True)
    p.add_argument("--release", default="", help="release id (default: a<ver>-<build>)")
    p.add_argument("--image-url", default="")
    p.add_argument("--image-sha256", default="")
    p.add_argument("--asset-base", default="", help="URL prefix the payloads publish under")
    p.add_argument("--report", default="", help="write the unclaimed file list here")
    p.add_argument("--strict", action="store_true",
                   help="fail when apks are unclaimed or a package is empty")
    return build(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
