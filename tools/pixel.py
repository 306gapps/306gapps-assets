#!/usr/bin/env python3
"""Discover Pixel OTA images from Google's published list.

The full OTA zip carries payload.bin with every partition, which is a smaller
and simpler download than the factory image for our purposes.
"""

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, asdict

OTA_URL = "https://developers.google.com/android/ota"
# The download pages sit behind a terms-of-service interstitial; this is the
# cookie the page itself sets once you accept.
TOS_COOKIE = "devsite_wall_acks=nexus-ota-tos"

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

_DEVICE = re.compile(
    r'<h2 id="(?P<codename>[a-z0-9_]+)"[^>]*data-text=\'"[^"]+" for (?P<name>[^\']+)\'',
)
_ROW = re.compile(
    r'<tr id="[^"]*">\s*'
    r'<td>(?P<label>[^<]*)</td>\s*'
    r'<td>\s*<a href="(?P<url>[^"]+)"[^>]*>[^<]*</a>\s*</td>\s*'
    r'<td>(?P<sha>[0-9a-f]{64})</td>',
    re.S,
)
_LABEL = re.compile(r"^(?P<version>[\d.]+)\s*\((?P<rest>.*)\)\s*$")


@dataclass(frozen=True)
class Build:
    device: str
    model: str
    version: str
    build_id: str
    month: str
    url: str
    sha256: str
    carrier: str = ""

    @property
    def generic(self) -> bool:
        """True for the unbranded worldwide build."""
        return not self.carrier

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    def sort_key(self) -> tuple:
        year, mon = 0, 0
        parts = self.month.split()
        if len(parts) == 2 and parts[0] in MONTHS:
            mon, year = MONTHS[parts[0]], int(parts[1])
        return (self.major, year, mon, self.build_id)


def parse(html: str) -> list[Build]:
    """Parse the OTA listing. Devices appear newest-first on the page, and that
    order is preserved in the result."""
    builds: list[Build] = []
    marks = [(m.start(), m.group("codename"), m.group("name"))
             for m in _DEVICE.finditer(html)]

    for i, (start, codename, model) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
        for row in _ROW.finditer(html, start, end):
            label = _LABEL.match(row.group("label").strip())
            if not label:
                continue
            fields = [f.strip() for f in label.group("rest").split(",")]
            if len(fields) < 2:
                continue
            builds.append(Build(
                device=codename,
                model=model,
                version=label.group("version"),
                build_id=fields[0],
                month=fields[1],
                carrier=", ".join(fields[2:]),
                url=row.group("url"),
                sha256=row.group("sha"),
            ))
    return builds


def newest(builds: list[Build], device: str = "", major: int = 0) -> Build | None:
    """Pick the newest generic build, preferring the device that appears first
    on the page -- Google lists the current flagship at the top."""
    order = {b.device: i for i, b in enumerate(builds)}
    pool = [b for b in builds if b.generic]
    if device:
        pool = [b for b in pool if b.device == device]
    if not pool:
        return None

    if not major:
        major = max(b.major for b in pool)
    pool = [b for b in pool if b.major == major]
    if not pool:
        return None

    lead = min(pool, key=lambda b: order[b.device]).device
    if not device:
        pool = [b for b in pool if b.device == lead]
    return max(pool, key=Build.sort_key)


def fetch(url: str = OTA_URL) -> str:
    req = urllib.request.Request(url, headers={
        "Cookie": TOS_COOKIE,
        "User-Agent": "306gapps-assets",
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device", default="", help="codename, e.g. cubs (default: newest)")
    p.add_argument("--major", type=int, default=0, help="Android major version")
    p.add_argument("--html", default="", help="parse a saved page instead of fetching")
    p.add_argument("--list-devices", action="store_true")
    args = p.parse_args()

    html = open(args.html, encoding="utf-8", errors="replace").read() if args.html else fetch()
    builds = parse(html)
    if not builds:
        print("error: no builds parsed - the page layout may have changed",
              file=sys.stderr)
        return 1

    if args.list_devices:
        seen = {}
        for b in builds:
            seen.setdefault(b.device, b.model)
        for codename, model in seen.items():
            print(f"{codename}\t{model}")
        return 0

    build = newest(builds, args.device, args.major)
    if not build:
        print("error: no matching generic build found", file=sys.stderr)
        return 1
    print(json.dumps(asdict(build), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
