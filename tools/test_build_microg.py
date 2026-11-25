import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

import build_microg as bm

HERE = Path(__file__).resolve().parent
DEFS = HERE.parent / "microg" / "microg.yaml"


class AllowlistTest(unittest.TestCase):
    XML = """<permissions>
      <privapp-permissions package="a.b" sha256-cert-digest="00">
        <permission name="android.permission.DUMP" />
        <permission name="android.permission.INSTALL_PACKAGES" />
      </privapp-permissions>
      <privapp-permissions package="c.d" sha256-cert-digest="00">
        <permission name="android.permission.MANAGE_USB" />
      </privapp-permissions>
    </permissions>"""

    def test_reads_only_the_named_package(self):
        self.assertEqual(bm.allowlisted(self.XML, "a.b"),
                         {"android.permission.DUMP", "android.permission.INSTALL_PACKAGES"})
        self.assertEqual(bm.allowlisted(self.XML, "c.d"), {"android.permission.MANAGE_USB"})
        self.assertEqual(bm.allowlisted(self.XML, "e.f"), set())


class ExpandTest(unittest.TestCase):
    def test_part_covers_every_partition(self):
        self.assertEqual(bm.expand("{part}/etc/x"),
                         ["system/etc/x", "system_ext/etc/x", "product/etc/x"])
        self.assertEqual(bm.expand("GmsCore"), ["GmsCore"])


class LibsTest(unittest.TestCase):
    def test_only_the_arch_is_unpacked_beside_the_apk(self):
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "x.apk"
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr("lib/arm64-v8a/liba.so", b"a")
                z.writestr("lib/armeabi-v7a/liba.so", b"b")
                z.writestr("lib/arm64-v8a/sub/libc.so", b"c")
                z.writestr("classes.dex", b"")
            got = bm.extract_libs(apk, "product/priv-app/GmsCore/GmsCore.apk", "arm64",
                                  Path(d) / "work")
            self.assertEqual([rel for _, rel in got],
                             ["product/priv-app/GmsCore/lib/arm64/liba.so"])
            self.assertEqual(got[0][0].read_bytes(), b"a")


class ReleaseIdTest(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(DEFS.read_text())
        self.resolved = {d["id"]: {"url": f"https://x/{d['id']}.apk", "version": "1"}
                         for d in self.doc["packages"]}
        self.resolved["microg"]["version"] = "v0.3.18.252432"

    def test_names_the_gms_version_and_is_stable(self):
        a = bm.release_id(self.doc, DEFS, self.resolved)
        self.assertTrue(a.startswith("microg-0.3.18.252432-"), a)
        self.assertEqual(a, bm.release_id(self.doc, DEFS, self.resolved))

    def test_any_apk_moving_changes_it(self):
        a = bm.release_id(self.doc, DEFS, self.resolved)
        self.resolved["aurorastore"]["url"] = "https://x/aurora-2.apk"
        self.assertNotEqual(a, bm.release_id(self.doc, DEFS, self.resolved))


class DefinitionsTest(unittest.TestCase):
    def test_every_config_file_exists_and_privapps_are_allowlisted(self):
        doc = yaml.safe_load(DEFS.read_text())
        groups = {g["id"] for g in doc["groups"]}
        for d in doc["packages"]:
            self.assertIn(d["group"], groups, d["id"])
            for f in d.get("files", []):
                self.assertTrue((DEFS.parent / f["src"]).is_file(), f["src"])
            if "/priv-app/" in d["apk"]["path"] and d["apk"]["package"] != "com.google.android.gsf":
                # Android only reads a priv-app's allowlist from its own partition.
                part = d["apk"]["path"].split("/", 1)[0]
                xml = "".join((DEFS.parent / f["src"]).read_text()
                              for f in d.get("files", [])
                              if f["path"].startswith(f"{part}/etc/permissions/"))
                self.assertIn(f'package="{d["apk"]["package"]}"', xml, d["id"])

    def test_no_removal_names_a_path_we_install(self):
        # A module masks a removal with a directory, which would hide our own file.
        doc = yaml.safe_load(DEFS.read_text())
        ours = set()
        for d in doc["packages"]:
            ours.add(d["apk"]["path"])
            ours.update(f["path"] for f in d.get("files", []))
        removals = [r for d in doc["packages"] for e in d.get("removes", []) for r in bm.expand(e)]
        removals += [r for e in doc.get("legacy", []) for r in bm.expand(e)]
        for r in removals:
            if "/" in r:
                self.assertNotIn(r, ours)


class PlacementTest(unittest.TestCase):
    def test_microg_itself_installs_to_system(self):
        doc = yaml.safe_load(DEFS.read_text())
        by = {d["id"]: d for d in doc["packages"]}
        for pid in ("microg", "microg-gsf"):
            self.assertTrue(by[pid]["apk"]["path"].startswith("system/"), pid)


class PublishFlavorTest(unittest.TestCase):
    def run_tool(self, d: Path, rid: str, build: str):
        m = d / "manifest.json"
        m.write_text(json.dumps({"release": {
            "id": rid, "flavor": "microg", "android": {"api": 33, "version": "13+"},
            "source": {"build": build}, "created": "2026-11-25T00:00:00Z",
            "asset_base": "https://example/microg"}}))
        subprocess.run([sys.executable, str(HERE / "publish_flavor.py"),
                        "--index", str(d / "index.json"), "--manifest", str(m),
                        "--repo", "o/r", "--branch", "microg",
                        "--changelog", str(d / "changelog.json")], check=True,
                       capture_output=True)
        return (json.loads((d / "index.json").read_text()),
                json.loads((d / "changelog.json").read_text()))

    def test_replaces_the_entry_and_logs_only_version_moves(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / "index.json").write_text(json.dumps(
                {"schema": 1, "releases": [{"id": "a17-x"}]}))
            idx, log = self.run_tool(d, "microg-1-aaaa", "1")
            self.assertEqual([f["id"] for f in idx["flavors"]], ["microg-1-aaaa"])
            self.assertEqual(idx["releases"], [{"id": "a17-x"}])
            self.assertEqual(len(log["entries"]), 1)

            idx, log = self.run_tool(d, "microg-1-bbbb", "1")
            self.assertEqual([f["id"] for f in idx["flavors"]], ["microg-1-bbbb"])
            self.assertEqual(len(log["entries"]), 1)

            idx, log = self.run_tool(d, "microg-2-cccc", "2")
            self.assertEqual(log["entries"][0]["title"], "microG 2")
            self.assertIn("up from 1", log["entries"][0]["body"])


if __name__ == "__main__":
    unittest.main()
