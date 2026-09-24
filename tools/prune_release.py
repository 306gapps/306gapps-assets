#!/usr/bin/env python3
"""Remove release assets that no manifest references.

Uploading with --clobber replaces and adds but never removes, so a re-dump
that drops files leaves the old payloads behind forever. The dump workflow
prunes as it goes; this is for releases published before it did, and for
checking by hand.
"""

import argparse
import base64
import json
import subprocess
import sys


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=True).stdout


def manifest_for(repo: str, branch: str, release: str) -> dict:
    raw = gh("api", f"repos/{repo}/contents/releases/{release}/manifest.json"
                    f"?ref={branch}", "--jq", ".content")
    return json.loads(base64.b64decode(raw))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--release", required=True, help="release tag")
    p.add_argument("--branch", default="", help="branch holding the manifest "
                                                "(default: from the release id)")
    p.add_argument("--apply", action="store_true",
                   help="actually delete; without it, only report")
    args = p.parse_args()

    branch = args.branch or args.release.split("-", 1)[0]
    m = manifest_for(args.repo, branch, args.release)
    want = {f["asset"] for p_ in m["packages"] for f in p_["files"] if f.get("asset")}
    have = set(gh("api", f"repos/{args.repo}/releases/tags/{args.release}",
                  "--jq", ".assets[].name").split())

    missing = want - have
    stale = have - want
    print(f"{args.release}: manifest needs {len(want)}, release has {len(have)}")

    if missing:
        # Never prune when something is already absent: the release is broken
        # in a way deleting more cannot fix.
        print(f"error: {len(missing)} payload(s) missing from the release; "
              f"re-run the dump rather than pruning", file=sys.stderr)
        for n in sorted(missing)[:10]:
            print(f"  {n}", file=sys.stderr)
        return 1

    if not stale:
        print("  nothing to prune")
        return 0

    for n in sorted(stale):
        if args.apply:
            print(f"  deleting {n}")
            gh("release", "delete-asset", args.release, n,
               "--repo", args.repo, "--yes")
        else:
            print(f"  would delete {n}")
    if not args.apply:
        print(f"\n{len(stale)} unreferenced asset(s); pass --apply to remove them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
