#!/usr/bin/env python3
"""Record a flavor release (microG) in index.json, replacing the previous one.

Flavors live under their own key so builders that predate them never offer
one: their installer would demand an exact API match.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", default="index.json")
    p.add_argument("--manifest", required=True)
    p.add_argument("--repo", required=True, help="owner/name of the assets repo")
    p.add_argument("--branch", required=True, help="branch the manifest is committed to")
    p.add_argument("--changelog", default="",
                   help="changelog.json to add an entry to when the version moves")
    args = p.parse_args()

    rel = json.loads(Path(args.manifest).read_text())["release"]
    flavor = rel["flavor"]
    entry = {
        "id": rel["id"],
        "flavor": flavor,
        "android": rel["android"],
        "device": "",
        "build": rel["source"]["build"],
        "branch": args.branch,
        "created": rel["created"],
        "manifest": (f"https://raw.githubusercontent.com/{args.repo}/"
                     f"{args.branch}/releases/{rel['id']}/manifest.json"),
        "asset_base": rel["asset_base"],
    }

    path = Path(args.index)
    index = json.loads(path.read_text())
    previous = next((f for f in index.get("flavors", []) if f.get("flavor") == flavor), None)
    index["flavors"] = [f for f in index.get("flavors", []) if f.get("flavor") != flavor]
    index["flavors"].append(entry)
    index["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(index, indent=2) + "\n")
    print(f"{path}: {flavor} is now {rel['id']}")

    if args.changelog and (previous is None or previous.get("build") != entry["build"]):
        log = Path(args.changelog)
        doc = json.loads(log.read_text()) if log.exists() else {"schema": 1, "entries": []}
        doc["entries"].insert(0, {
            "date": entry["created"][:10],
            "title": f"microG {entry['build']}",
            "body": (f"The microG release now carries microG {entry['build']}"
                     + (f", up from {previous['build']}." if previous else ".")),
        })
        log.write_text(json.dumps(doc, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
