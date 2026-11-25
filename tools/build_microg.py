#!/usr/bin/env python3
"""Build the microG release: resolve, download and verify each apk, then emit
a manifest plus asset bundle the builder reads like any dumped release.

With --resolve-only nothing is downloaded; it prints the release id the
current upstream versions would produce, which is all the daily check needs.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from axml import manifest_attributes, package_name
from build_manifest import SCHEMA, classify, publish_asset, sha256_of

UA = "306gapps-assets (+https://github.com/306gapps/306gapps-assets)"
PARTITIONS = ("system", "system_ext", "product")

# apk ABI directory -> the directory Android extracts system app libs to.
LIB_DIRS = {"arm64": ("arm64-v8a", "arm64"), "arm": ("armeabi-v7a", "arm")}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    tmp.replace(dest)


# ---------------------------------------------------------------- resolvers

_fdroid_index: dict[str, dict] = {}
_no_api: set[str] = set()


def resolve_fdroid(repo: str, package: str) -> dict | None:
    """Newest build of package in an F-Droid repo: url, version, and sha256 if known."""
    repo = repo.rstrip("/")
    base = repo[:-len("/repo")] if repo.endswith("/repo") else repo
    # The per-package API is far cheaper than f-droid.org's or Izzy's index,
    # but repo.microg.org does not serve it.
    if base not in _no_api:
        try:
            data = json.loads(fetch(f"{base}/api/v1/packages/{package}", 60))
            code = max(int(v["versionCode"]) for v in data["packages"])
            name = next(str(v.get("versionName") or code)
                        for v in data["packages"] if int(v["versionCode"]) == code)
            return {"url": f"{repo}/{package}_{code}.apk", "version": name,
                    "code": code}
        except Exception as e:  # noqa: BLE001
            log(f"    {base} API: {e}; reading the index")
            _no_api.add(base)

    if repo not in _fdroid_index:
        blob = fetch(f"{repo}/index-v1.jar", 300)
        _fdroid_index[repo] = json.loads(
            zipfile.ZipFile(io.BytesIO(blob)).read("index-v1.json"))
    builds = _fdroid_index[repo].get("packages", {}).get(package)
    if not builds:
        return None
    best = max(builds, key=lambda v: int(v["versionCode"]))
    out = {"url": f"{repo}/{best['apkName']}",
           "version": str(best.get("versionName") or best["versionCode"]),
           "code": int(best["versionCode"])}
    if best.get("hashType") == "sha256" and best.get("hash"):
        out["sha256"] = best["hash"]
    return out


_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def resolve_gitlab(project: str, pattern: str) -> dict | None:
    """Newest release whose description links an apk matching pattern.

    The project pastes /uploads/ links into the description rather than
    attaching release assets.
    """
    rx = re.compile(pattern)
    api = (f"https://gitlab.com/api/v4/projects/"
           f"{urllib.parse.quote(project, safe='')}/releases?per_page=20")
    for rel in json.loads(fetch(api, 60)):
        for name, href in _MD_LINK.findall(rel.get("description") or ""):
            if rx.search(name.strip()):
                if href.startswith("/"):
                    href = f"https://gitlab.com/{project}{href}"
                return {"url": href, "version": str(rel.get("tag_name") or "")}
    return None


def resolve(apk: dict) -> dict:
    try:
        if "fdroid" in apk:
            got = resolve_fdroid(apk["fdroid"], apk["package"])
        elif "gitlab" in apk:
            got = resolve_gitlab(apk["gitlab"], apk["asset"])
        else:
            got = None
    except Exception as e:  # noqa: BLE001
        log(f"    resolution failed: {e}")
        got = None
    if got:
        return got
    if apk.get("url"):
        log(f"    falling back to the pinned {apk['url']}")
        return {"url": apk["url"], "version": ""}
    raise SystemExit(f"error: cannot resolve {apk['package']} and no url is pinned")


# ------------------------------------------------------------- verification

def cert_sha256(apk: Path) -> str:
    """Digest of the v1 signing certificate, as privapp-permissions pins it."""
    with zipfile.ZipFile(apk) as z:
        blocks = sorted(n for n in z.namelist()
                        if n.upper().startswith("META-INF/")
                        and n.upper().endswith((".RSA", ".DSA", ".EC")))
        if not blocks:
            raise SystemExit(f"error: {apk.name} has no v1 signature block "
                             "to read the certificate from")
        der = z.read(blocks[0])
    pem = subprocess.run(["openssl", "pkcs7", "-inform", "DER", "-print_certs"],
                         input=der, capture_output=True, check=True).stdout.decode()
    first = pem.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    cert = subprocess.run(["openssl", "x509", "-outform", "DER"],
                          input=first.encode(), capture_output=True, check=True).stdout
    return hashlib.sha256(cert).hexdigest().upper()


def android_sdk_tools() -> tuple[str, str] | None:
    """aapt2 and the newest android.jar, when an SDK is installed."""
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        return None
    aapt2 = sorted(Path(sdk, "build-tools").glob("*/aapt2"),
                   key=lambda p: [int(x) if x.isdigit() else 0
                                  for x in re.split(r"[.-]", p.parent.name)])
    jars = sorted(Path(sdk, "platforms").glob("android-*/android.jar"),
                  key=lambda p: [int(x) for x in re.findall(r"\d+", p.parent.name)])
    if not aapt2 or not jars:
        return None
    return str(aapt2[-1]), str(jars[-1])


PROTECTION_PRIVILEGED = 0x10


def privileged_permissions(aapt2: str, framework: str) -> set[str]:
    out = subprocess.run([aapt2, "dump", "xmltree", framework,
                          "--file", "AndroidManifest.xml"],
                         capture_output=True, text=True, check=True).stdout
    names = set()
    for block in re.split(r"\n\s+E: ", out):
        if not block.startswith("permission "):
            continue
        name = re.search(r':name\(0x01010003\)="([^"]+)"', block)
        level = re.search(r":protectionLevel\(0x01010009\)=(0x[0-9a-f]+)", block)
        if name and level and int(level.group(1), 16) & PROTECTION_PRIVILEGED:
            names.add(name.group(1))
    return names


def requested_permissions(aapt2: str, apk: Path) -> set[str]:
    out = subprocess.run([aapt2, "dump", "permissions", str(apk)],
                         capture_output=True, text=True, check=True).stdout
    return set(re.findall(r"^uses-permission: name='([^']+)'", out, re.M))


def allowlisted(xml: str, package: str) -> set[str]:
    m = re.search(rf'<privapp-permissions\s+package="{re.escape(package)}"'
                  r'.*?</privapp-permissions>', xml, re.S)
    return set(re.findall(r'<permission\s+name="([^"]+)"', m.group(0))) if m else set()


# ------------------------------------------------------------------- build

def expand(entry: str) -> list[str]:
    if "{part}" not in entry:
        return [entry]
    return [entry.format(part=p) for p in PARTITIONS]


def release_id(doc: dict, defs: Path, resolved: dict[str, dict]) -> str:
    """Changes whenever an apk, the definitions or a config file changes."""
    h = hashlib.sha256(defs.read_bytes())
    for src in sorted({f["src"] for d in doc["packages"] for f in d.get("files", [])}):
        h.update((defs.parent / src).read_bytes())
    for pid in sorted(resolved):
        h.update(f"{pid}={resolved[pid]['url']}\n".encode())
    gms = next(resolved[d["id"]]["version"] for d in doc["packages"]
               if d["apk"]["package"] == "com.google.android.gms")
    return f"microg-{gms.lstrip('v')}-{h.hexdigest()[:8]}"


def extract_libs(apk: Path, apk_path: str, arch: str, work: Path) -> list[tuple[Path, str]]:
    """Unpack the arch's native libs beside the apk, as a system app needs."""
    abi, libdir = LIB_DIRS[arch]
    out = []
    target = f"{os.path.dirname(apk_path)}/lib/{libdir}"
    with zipfile.ZipFile(apk) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if len(parts) != 3 or parts[:2] != ["lib", abi] or not parts[2].endswith(".so"):
                continue
            dest = work / "libs" / libdir / parts[2]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            out.append((dest, f"{target}/{parts[2]}"))
    return sorted(out, key=lambda t: t[1])


def entry_for(src: Path, rel: str, assets: Path) -> dict:
    digest, size = sha256_of(src)
    entry = publish_asset(src, digest, size, rel, assets)
    entry["mode"] = "0644"
    entry["kind"] = classify(rel)
    return entry


def build(args) -> int:
    defs = Path(args.definitions)
    doc = yaml.safe_load(defs.read_text())
    arch = doc.get("arch", "arm64")
    packages = doc["packages"]

    resolved = {}
    for d in packages:
        log(f"==> {d['name']} ({d['apk']['package']})")
        resolved[d["id"]] = resolve(d["apk"])
        log(f"    {resolved[d['id']]['version'] or 'pinned'} -> {resolved[d['id']]['url']}")

    rid = release_id(doc, defs, resolved)
    if args.resolve_only:
        print(rid)
        return 0

    sdk = android_sdk_tools()
    if sdk is None:
        if args.require_sdk:
            log("error: no Android SDK (aapt2 and android.jar) to check permissions with")
            return 1
        log("warning: no Android SDK; skipping the privileged permission check")
    privileged = privileged_permissions(*sdk) if sdk else set()

    assets = Path(args.assets)
    assets.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="microg-"))
    problems = []
    out_packages = []
    try:
        for d in packages:
            a, got = d["apk"], resolved[d["id"]]
            apk = work / os.path.basename(a["path"])
            download(got["url"], apk)

            if want := got.get("sha256"):
                if sha256_of(apk)[0] != want:
                    problems.append(f"{d['id']}: {got['url']} does not match the "
                                    "digest its repo index publishes")
                    continue
            cert = cert_sha256(apk)
            if cert != a["cert"].upper():
                problems.append(f"{d['id']}: signed by {cert}, expected {a['cert']}; "
                                "refusing it until the new key is checked by hand")
                continue
            with zipfile.ZipFile(apk) as z:
                manifest_xml = z.read("AndroidManifest.xml")
            if (pid := package_name(manifest_xml)) != a["package"]:
                problems.append(f"{d['id']}: apk declares {pid}, expected {a['package']}")
                continue
            attrs = manifest_attributes(manifest_xml)

            files = [entry_for(apk, a["path"], assets)]
            if a.get("libs"):
                files += [entry_for(src, rel, assets)
                          for src, rel in extract_libs(apk, a["path"], arch, work)]
            for f in d.get("files", []):
                files.append(entry_for(defs.parent / f["src"], f["path"], assets))

            if sdk and "/priv-app/" in a["path"]:
                allow = set()
                part = a["path"].split("/", 1)[0]
                for f in d.get("files", []):
                    if f["path"].startswith(f"{part}/etc/permissions/"):
                        allow |= allowlisted((defs.parent / f["src"]).read_text(),
                                             a["package"])
                missing = (requested_permissions(sdk[0], apk) & privileged) - allow
                if missing:
                    problems.append(
                        f"{d['id']}: requests privileged permission(s) no allowlist "
                        f"grants, which bootloops an enforcing device: "
                        f"{', '.join(sorted(missing))}")

            pkg = {
                "id": d["id"],
                "name": d["name"],
                "group": d["group"],
                "packages": [a["package"]],
                "files": sorted(files, key=lambda e: e["path"]),
            }
            version = {k: attrs[k] for k in ("versionCode", "versionName") if k in attrs}
            if version:
                pkg["version"] = version
            for key in ("summary", "required", "default", "requires", "conflicts"):
                if d.get(key):
                    pkg[key] = d[key]
            removes = [r for e in d.get("removes", []) for r in expand(e)]
            if d is packages[0]:
                removes += [r for e in doc.get("legacy", []) for r in expand(e)]
            if removes:
                pkg["removes"] = removes
            out_packages.append(pkg)
            apk.unlink()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if problems:
        for p in problems:
            log(f"error: {p}")
        return 1

    gms = next(p for p in out_packages if "com.google.android.gms" in p["packages"])
    min_api = int(doc["min_api"])
    manifest = {
        "schema": SCHEMA,
        "release": {
            "id": rid,
            "flavor": "microg",
            "android": {"api": min_api, "version": f"{api_version(min_api)}+",
                        "codename": ""},
            "min_api": min_api,
            "source": {"device": "", "build": gms.get("version", {}).get("versionName", ""),
                       "image": "", "sha256": ""},
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "asset_base": args.asset_base,
            "definitions": hashlib.sha256(defs.read_bytes()).hexdigest(),
        },
        "groups": doc["groups"],
        "packages": out_packages,
    }
    if arch != "arm64":
        manifest["release"]["arch"] = arch

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(f["size"] for p in out_packages for f in p["files"])
    log(f"{out}: {rid}, {len(out_packages)} packages, {total / 1048576:.1f} MiB")
    return 0


def api_version(api: int) -> str:
    """Android version for an API level, for display."""
    return {33: "13", 34: "14", 35: "15", 36: "16", 37: "17"}.get(api, f"API {api}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--definitions", default="microg/microg.yaml")
    p.add_argument("--assets", default="out/assets")
    p.add_argument("--out", default="out/manifest.json")
    p.add_argument("--asset-base", default="")
    p.add_argument("--resolve-only", action="store_true",
                   help="print the release id upstream would produce, download nothing")
    p.add_argument("--require-sdk", action="store_true",
                   help="fail rather than skip the privileged permission check")
    return build(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
