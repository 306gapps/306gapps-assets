#!/usr/bin/env python3
"""Suggest fixes for package definitions that matched nothing.

A package can match nothing for two very different reasons: the glob is wrong
for this release, or the app genuinely is not in this dump. Grepping by hand
does not distinguish them reliably, so this pairs each empty package against
the unclaimed paths and reports the closest candidates.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import yaml


# Words that appear in half the directory names in a dump and so carry no
# information: matching on them pairs GoogleKeepPrebuilt with FilesPrebuilt.
NOISE = re.compile(r"(Prebuilt|Release|Stub|Google|Pixel|Android|com\.google\.android\.)",
                   re.IGNORECASE)
VERSIONED = re.compile(r"[-_]v?[0-9][0-9._]*$")
APP_DIR = re.compile(r"/(app|priv-app|apex|framework)/")


def stem(glob: str) -> str:
    """The distinctive directory name a glob is really looking for."""
    parts = [p for p in glob.split("/") if p not in ("**", "*")]
    if not parts:
        return ""
    return parts[-1].replace("*", "").removesuffix(".xml").removesuffix(".apk")


def core(name: str) -> str:
    """Strip version suffixes and words common to most names."""
    return NOISE.sub("", VERSIONED.sub("", name)).strip("_-.")


def directories(paths: list[str]) -> dict[str, str]:
    """Map each app directory in the dump to its full path."""
    out = {}
    for p in paths:
        m = re.match(r"([^/]+)/(app|priv-app|apex|framework)/([^/]+)", p)
        if m:
            out[m.group(3)] = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--packages", required=True, help="definition yaml")
    p.add_argument("--manifest", required=True, help="manifest the dump produced")
    p.add_argument("--unclaimed", required=True, help="unclaimed.txt from the dump")
    p.add_argument("--cutoff", type=float, default=0.6,
                   help="similarity threshold, 0-1")
    args = p.parse_args()

    defs = yaml.safe_load(Path(args.packages).read_text())["packages"]
    built = {p["id"] for p in json.loads(Path(args.manifest).read_text())["packages"]}
    unclaimed = Path(args.unclaimed).read_text().split()

    empty = [d for d in defs if d["id"] not in built]
    if not empty:
        print("every package matched something")
        return 0

    dirs = directories(unclaimed)
    cores = {core(k): k for k in dirs if core(k)}
    print(f"{len(empty)} package(s) matched nothing in this dump\n")

    for d in empty:
        print(f"{d['id']} ({d['name']})")
        hits: dict[str, str] = {}
        for glob in d.get("include", []):
            # Only globs naming an app directory are worth pairing against
            # directories; a permissions xml shares no vocabulary with one.
            if not APP_DIR.search(glob):
                continue
            want = core(stem(glob))
            if len(want) < 5:
                continue
            for match in difflib.get_close_matches(want, cores, n=3, cutoff=args.cutoff):
                hits[dirs[cores[match]]] = glob
            for c, name in cores.items():
                # Substring both ways, but only for names long enough that a
                # coincidental overlap is unlikely.
                if len(c) >= 5 and (want.lower() in c.lower() or c.lower() in want.lower()):
                    hits[dirs[name]] = glob

        if hits:
            for path, glob in sorted(hits.items()):
                print(f"  {path}")
                print(f"      would be claimed by adjusting: {glob}")
        else:
            print("  nothing resembling it in the dump; the app is most likely "
                  "not shipped on this release")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
