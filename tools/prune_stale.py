#!/usr/bin/env python3
"""Delete releases superseded by a newer one for the same Android version.

Changing the device a version is dumped from changes the build id, so the old
release is not replaced in place; it just sits there holding a gigabyte of
payloads nobody can reach. The index only ever serves the newest per version.

Dry run by default. Pass --delete to act.
"""

import argparse
import json
import subprocess
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/{repo}/main/index.json"


def gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=check).stdout


def stale(index: dict) -> list[dict]:
    newest: dict[int, dict] = {}
    for r in index.get("releases", []):
        api = r["android"]["api"]
        if api not in newest or r["created"] > newest[api]["created"]:
            newest[api] = r
    keep = {r["id"] for r in newest.values()}
    return [r for r in index.get("releases", []) if r["id"] not in keep]


def drop_from_branch(repo: str, r: dict) -> None:
    """Remove a release's manifest from its version branch.

    The index is rebuilt from those manifests, so leaving one behind brings the
    entry straight back pointing at assets that no longer exist.
    """
    branch = f"a{r['android']['version']}"
    path = f"releases/{r['id']}"
    subprocess.run(["git", "fetch", "-q", "origin",
                    f"refs/heads/{branch}:refs/remotes/origin/{branch}"], check=False)
    wt = f"/tmp/prune-{branch}"
    subprocess.run(["rm", "-rf", wt], check=False)
    subprocess.run(["git", "worktree", "add", "-q", wt, f"origin/{branch}"], check=True)
    try:
        subprocess.run(["git", "checkout", "-q", "-B", branch, f"origin/{branch}"],
                       cwd=wt, check=True)
        subprocess.run(["git", "rm", "-rq", path], cwd=wt, check=True)
        subprocess.run(["git", "commit", "-q", "-m",
                        f"Remove the superseded {r['device']} release"], cwd=wt, check=True)
        subprocess.run(["git", "push", "-q", "origin", branch], cwd=wt, check=True)
        print(f"  removed {path} from {branch}")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], check=False)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--delete", action="store_true")
    args = p.parse_args()

    with urllib.request.urlopen(RAW.format(repo=args.repo)) as f:
        index = json.load(f)

    victims = stale(index)
    if not victims:
        print("nothing stale")
        return 0

    for r in victims:
        keep = next(x["id"] for x in index["releases"]
                    if x["android"]["api"] == r["android"]["api"]
                    and x["id"] not in {v["id"] for v in victims})
        print(f"{r['id']} ({r['device']} {r['build']}) superseded by {keep}")
        if not args.delete:
            continue
        gh("release", "delete", r["id"], "--repo", args.repo, "--yes",
           "--cleanup-tag", check=False)
        print("  deleted release and tag")
        drop_from_branch(args.repo, r)
    if not args.delete:
        print("\ndry run; pass --delete to remove them")
        return 0

    print("\nnow rebuild the index:")
    print(f"  python3 tools/rebuild_index.py --repo {args.repo} --index index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
