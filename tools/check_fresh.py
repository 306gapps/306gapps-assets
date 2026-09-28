#!/usr/bin/env python3
"""Report releases built from definitions that have since been edited.

Editing packages/a<N>.yaml changes nothing already published, and a stale
release looks no different from the outside. Compares the digest each release
recorded against the definitions as they stand now.
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=True).stdout


def published_manifest(repo: str, branch: str, release: str) -> dict | None:
    try:
        raw = gh("api", f"repos/{repo}/contents/releases/{release}/manifest.json"
                        f"?ref={branch}", "--jq", ".content")
    except subprocess.CalledProcessError:
        return None
    return json.loads(base64.b64decode(raw))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--index", default="index.json")
    p.add_argument("--packages", default="packages")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero when anything is stale")
    args = p.parse_args()

    index_path = Path(args.index)
    if not index_path.exists():
        print("no index yet; nothing to check")
        return 0
    releases = json.loads(index_path.read_text()).get("releases", [])

    stale = []
    for r in releases:
        major = r["branch"].lstrip("a")
        defs = Path(args.packages) / f"a{major}.yaml"
        if not defs.exists():
            print(f"  {r['id']}: no {defs} any more", file=sys.stderr)
            continue
        current = hashlib.sha256(defs.read_bytes()).hexdigest()

        m = published_manifest(args.repo, r["branch"], r["id"])
        recorded = (m or {}).get("release", {}).get("definitions")
        if recorded is None:
            print(f"  {r['id']}: predates definition tracking - re-dump to start recording")
            stale.append(r["id"])
        elif recorded != current:
            print(f"  {r['id']}: built from {recorded[:12]}, "
                  f"definitions are now {current[:12]}")
            stale.append(r["id"])
        else:
            print(f"  {r['id']}: up to date")

    if stale:
        print(f"\n{len(stale)} release(s) predate the current definitions; "
              f"re-run the dump workflow with force", file=sys.stderr)
        return 1 if args.strict else 0
    print("\nevery release matches the definitions it was built from")
    return 0


if __name__ == "__main__":
    sys.exit(main())
