#!/usr/bin/env python3
"""Decide which releases need dumping.

The support window is defined by which packages/a<N>.yaml files exist: add a
definition file and that Android version is supported, remove it and it is not.
For each supported version this finds the newest generic Pixel build and
reports whether the index already has it.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from pixel import fetch, newest, parse

DEFS = re.compile(r"^a(\d+)\.yaml$")


def supported_versions(defs_dir: Path) -> dict[int, Path]:
    """Map Android major version to its definition file."""
    out = {}
    for path in sorted(defs_dir.glob("a*.yaml")):
        m = DEFS.match(path.name)
        if m:
            out[int(m.group(1))] = path
    return out


def published(index_path: Path) -> set[str]:
    if not index_path.exists():
        return set()
    doc = json.loads(index_path.read_text())
    return {r["id"] for r in doc.get("releases", [])}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--packages", default="packages", help="definition directory")
    p.add_argument("--index", default="index.json")
    p.add_argument("--html", default="", help="parse a saved OTA page instead of fetching")
    p.add_argument("--only", type=int, default=0, help="plan just this Android version")
    p.add_argument("--force", action="store_true", help="include already-published builds")
    p.add_argument("--github-output", default="", help="write a matrix for Actions here")
    args = p.parse_args()

    versions = supported_versions(Path(args.packages))
    if not versions:
        print(f"error: no a<N>.yaml files in {args.packages}", file=sys.stderr)
        return 1
    if args.only:
        if args.only not in versions:
            print(f"error: Android {args.only} is not supported "
                  f"(no {args.packages}/a{args.only}.yaml)", file=sys.stderr)
            return 1
        versions = {args.only: versions[args.only]}

    html = Path(args.html).read_text(errors="replace") if args.html else fetch()
    builds = parse(html)
    if not builds:
        print("error: no builds parsed; the OTA page layout may have changed",
              file=sys.stderr)
        return 1

    have = published(Path(args.index))
    plan = []
    for major in sorted(versions, reverse=True):
        build = newest(builds, major=major)
        if not build:
            print(f"  a{major}: no generic build listed", file=sys.stderr)
            continue
        release_id = f"a{major}-{build.build_id.lower()}"
        needed = args.force or release_id not in have
        state = "needs dump" if needed else "up to date"
        print(f"  a{major}: {release_id} via {build.device} "
              f"({build.model}, {build.month}) - {state}", file=sys.stderr)
        if needed:
            plan.append({
                "major": major,
                "release_id": release_id,
                "device": build.device,
                "model": build.model,
                "build_id": build.build_id,
                "url": build.url,
                "sha256": build.sha256,
                "defs": str(versions[major]),
            })

    print(json.dumps(plan, indent=2))

    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"matrix={json.dumps({'include': plan})}\n")
            f.write(f"any={'true' if plan else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
