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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from globmatch import matches

SCHEMA = 1
PARTITIONS = ("system", "system_ext", "product", "vendor")

# Files that are part of the ROM rather than of any Google app.
IGNORE = (
    "**/lost+found/**",
    "**/*.prop",
    "**/etc/selinux/**",
    "**/etc/fs_config_*",
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
    """Return every regular file under root, as partition-relative paths."""
    out = []
    for part in PARTITIONS:
        base = root / part
        if not base.is_dir():
            continue
        for dirpath, _, filenames in os.walk(base):
            for name in filenames:
                full = Path(dirpath) / name
                if not full.is_file() or full.is_symlink():
                    continue
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


def interesting(path: str) -> bool:
    """Unclaimed noise is not worth reporting; an unclaimed app is."""
    return path.endswith(".apk")


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
    for d in defs:
        entries = []
        for rel in by_package[d["id"]]:
            full = root / rel
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
                "mode": f"{full.stat().st_mode & 0o7777:04o}",
                "context": selinux_context(full),
                "kind": classify(rel),
            })

        if not entries:
            empty.append(d["id"])
            continue

        pkg = {
            "id": d["id"],
            "name": d["name"],
            "category": d.get("category", "extras"),
            "files": sorted(entries, key=lambda e: e["path"]),
        }
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

    if problems := check_references(packages):
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        return 1

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

    notable = [f for f in unclaimed if interesting(f)]
    if notable:
        print(f"\nwarning: {len(notable)} unclaimed apk(s) -- "
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
