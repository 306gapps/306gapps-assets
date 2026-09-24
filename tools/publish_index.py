#!/usr/bin/env python3
"""Add a release to index.json, the catalogue the builder reads first."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1


def load(path: Path) -> dict:
    if path.exists():
        doc = json.loads(path.read_text())
        if doc.get("schema") != SCHEMA:
            raise SystemExit(f"{path}: schema {doc.get('schema')} != {SCHEMA}")
        return doc
    return {"schema": SCHEMA, "repo": "", "updated": "", "releases": []}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", default="index.json")
    p.add_argument("--manifest", required=True, help="the release manifest just built")
    p.add_argument("--repo", required=True, help="owner/name of the assets repo")
    p.add_argument("--branch", required=True, help="branch the manifest is committed to")
    p.add_argument("--asset-base", required=True, help="URL prefix the payloads live under")
    p.add_argument("--keep", type=int, default=6,
                   help="releases to keep per Android version")
    args = p.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    rel = manifest["release"]

    entry = {
        "id": rel["id"],
        "android": rel["android"],
        "device": rel["source"]["device"],
        "build": rel["source"]["build"],
        "branch": args.branch,
        "created": rel["created"],
        "manifest": (f"https://raw.githubusercontent.com/{args.repo}/"
                     f"{args.branch}/releases/{rel['id']}/manifest.json"),
        "asset_base": args.asset_base,
    }

    index = load(Path(args.index))
    index["repo"] = args.repo
    index["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    releases = [r for r in index["releases"] if r["id"] != entry["id"]]
    releases.append(entry)

    # Keep the catalogue small: the newest few builds per Android version.
    kept: list[dict] = []
    by_api: dict[int, list[dict]] = {}
    for r in sorted(releases, key=lambda r: r["created"], reverse=True):
        by_api.setdefault(r["android"]["api"], []).append(r)
    for api in sorted(by_api, reverse=True):
        kept.extend(by_api[api][:args.keep])

    index["releases"] = kept
    Path(args.index).write_text(json.dumps(index, indent=2) + "\n")

    dropped = len(releases) - len(kept)
    print(f"{args.index}: {entry['id']} published, {len(kept)} releases listed"
          + (f", {dropped} retired" if dropped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
