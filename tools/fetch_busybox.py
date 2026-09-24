#!/usr/bin/env python3
"""Publish the static busybox the recovery installer bundles.

Recovery environments differ wildly in which applets they ship and how those
applets behave, so the installer carries its own. Magisk builds a static
busybox for every Android ABI and ships it inside its apk; that build is
well-tested across exactly the devices and recoveries we care about, so it is
what we republish.

BusyBox is GPLv2. Republishing the binary carries the obligation to offer the
corresponding source, which the emitted NOTICE does.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

MAGISK_RELEASES = "https://api.github.com/repos/topjohnwu/Magisk/releases/latest"

# Android ABI inside the apk -> the architecture name a release manifest uses.
ABIS = {
    "arm64-v8a": "arm64",
    "armeabi-v7a": "arm",
    "x86_64": "x86_64",
    "x86": "x86",
}

NOTICE = """\
BusyBox, as built and distributed by the Magisk project ({version}).

BusyBox is free software licensed under the GNU General Public License
version 2, Copyright (C) its many contributors. The binary published here is
unmodified.

Complete corresponding source code is available from:
  https://github.com/topjohnwu/ndk-busybox
  https://busybox.net/

Source: {source}
"""


def get(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": "306gapps-assets"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    return data if binary else json.loads(data)


def pick_apk(release: dict) -> tuple[str, str]:
    """Prefer the release apk over the debug build."""
    apks = [a for a in release["assets"] if a["name"].endswith(".apk")]
    if not apks:
        raise SystemExit("no apk in the latest Magisk release")
    apks.sort(key=lambda a: ("debug" in a["name"].lower(), a["name"]))
    return apks[0]["browser_download_url"], apks[0]["name"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="tools/busybox", help="directory to write binaries to")
    p.add_argument("--arch", action="append", default=[],
                   help="architectures to publish (default: arm64, arm)")
    p.add_argument("--json", default="", help="also write the index fragment here")
    args = p.parse_args()

    wanted = args.arch or ["arm64", "arm"]
    by_arch = {v: k for k, v in ABIS.items()}
    unknown = [a for a in wanted if a not in by_arch]
    if unknown:
        raise SystemExit(f"unknown architecture(s): {', '.join(unknown)}")

    release = get(MAGISK_RELEASES)
    url, name = pick_apk(release)
    version = f"1.36.1 ({release['tag_name']})"
    print(f"magisk {release['tag_name']}: {name}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    apk = out / ".magisk.apk"
    apk.write_bytes(get(url, binary=True))

    fragment = {}
    try:
        with zipfile.ZipFile(apk) as z:
            for arch in wanted:
                member = f"lib/{by_arch[arch]}/libbusybox.so"
                try:
                    data = z.read(member)
                except KeyError:
                    print(f"warning: {member} not in the apk", file=sys.stderr)
                    continue
                if not data.startswith(b"\x7fELF"):
                    raise SystemExit(f"{member} is not an ELF binary")

                digest = hashlib.sha256(data).hexdigest()
                asset = f"busybox-{arch}"
                (out / asset).write_bytes(data)
                fragment[arch] = {
                    "asset": asset, "sha256": digest,
                    "size": len(data), "version": version,
                }
                print(f"  {arch:8s} {len(data):>9,} bytes  {digest[:16]}...")
    finally:
        apk.unlink(missing_ok=True)

    if not fragment:
        raise SystemExit("no busybox binaries extracted")

    (out / "NOTICE").write_text(NOTICE.format(version=version, source=url))

    if args.json:
        Path(args.json).write_text(json.dumps({"busybox": fragment}, indent=2) + "\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
