#!/usr/bin/env python3
"""Rebuild index.json from what is actually published.

The index is written last in a dump, so a failure after the payloads are up
leaves releases that exist but are not listed. This reconstructs the index from
the published releases and the manifests on the version branches, which are the
real record.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=True).stdout


def branches(repo: str) -> list[str]:
    out = gh("api", f"repos/{repo}/branches", "--jq", ".[].name")
    return [b for b in out.split() if b.startswith("a") and b[1:].isdigit()]


def manifests_on(repo: str, branch: str) -> list[str]:
    try:
        out = gh("api", f"repos/{repo}/contents/releases?ref={branch}",
                 "--jq", ".[] | select(.type==\"dir\") | .name")
    except subprocess.CalledProcessError:
        return []
    return out.split()


def read_manifest(repo: str, branch: str, release: str) -> dict | None:
    try:
        raw = gh("api",
                 f"repos/{repo}/contents/releases/{release}/manifest.json?ref={branch}",
                 "--jq", ".content")
    except subprocess.CalledProcessError:
        return None
    import base64
    return json.loads(base64.b64decode(raw))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, help="owner/name")
    p.add_argument("--index", default="index.json")
    p.add_argument("--keep", type=int, default=6,
                   help="releases to keep per Android version")
    args = p.parse_args()

    existing = {}
    idx_path = Path(args.index)
    if idx_path.exists():
        doc = json.loads(idx_path.read_text())
        existing = {"tools": doc.get("tools", {})}

    entries = []
    for branch in sorted(branches(args.repo), reverse=True):
        for release in manifests_on(args.repo, branch):
            m = read_manifest(args.repo, branch, release)
            if not m:
                print(f"  {branch}/{release}: no manifest", file=sys.stderr)
                continue
            rel = m["release"]
            entries.append({
                "id": rel["id"],
                "android": rel["android"],
                "device": rel["source"]["device"],
                "build": rel["source"]["build"],
                "branch": branch,
                "created": rel["created"],
                "manifest": (f"https://raw.githubusercontent.com/{args.repo}/"
                             f"{branch}/releases/{rel['id']}/manifest.json"),
                "asset_base": (f"https://github.com/{args.repo}/releases/"
                               f"download/{rel['id']}"),
            })
            print(f"  {rel['id']}: {len(m['packages'])} packages", file=sys.stderr)

    by_api: dict[int, list[dict]] = {}
    for r in sorted(entries, key=lambda r: r["created"], reverse=True):
        by_api.setdefault(r["android"]["api"], []).append(r)
    kept = [r for api in sorted(by_api, reverse=True) for r in by_api[api][:args.keep]]

    doc = {
        "schema": SCHEMA,
        "repo": args.repo,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "releases": kept,
    }
    if existing.get("tools"):
        doc["tools"] = existing["tools"]

    idx_path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"{args.index}: {len(kept)} release(s) listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
