import unittest
from pathlib import Path

import build_manifest as bm


def pkg(pid, **kw):
    return {"id": pid, "files": [], **kw}


class TestPruneConflicts(unittest.TestCase):
    """The definitions cover every Android version; a release ships a subset."""

    def test_conflict_with_a_package_the_release_lacks_is_dropped(self):
        # The verifier only exists from Android 16, so the conflict points at
        # nothing on older releases.
        pkgs = [pkg("gmscore"), pkg("verifier-block", conflicts=["verifier"])]
        dropped = bm.prune_conflicts(pkgs)
        self.assertEqual(len(dropped), 1)
        self.assertIn("verifier", dropped[0])
        self.assertNotIn("conflicts", pkgs[1])

    def test_conflict_between_two_shipped_packages_is_kept(self):
        pkgs = [pkg("dialer-google"), pkg("dialer-aosp", conflicts=["dialer-google"])]
        self.assertEqual(bm.prune_conflicts(pkgs), [])
        self.assertEqual(pkgs[1]["conflicts"], ["dialer-google"])

    def test_only_the_missing_half_is_dropped(self):
        pkgs = [pkg("a"), pkg("b", conflicts=["a", "gone"])]
        bm.prune_conflicts(pkgs)
        self.assertEqual(pkgs[1]["conflicts"], ["a"])


class TestCheckReferences(unittest.TestCase):
    def test_a_missing_requires_is_still_an_error(self):
        # Unlike a conflict, a package cannot work without what it depends on.
        problems = bm.check_references([pkg("chrome", requires=["trichrome"])])
        self.assertEqual(len(problems), 1)
        self.assertIn("trichrome", problems[0])

    def test_a_satisfied_requires_passes(self):
        pkgs = [pkg("trichrome"), pkg("chrome", requires=["trichrome"])]
        self.assertEqual(bm.check_references(pkgs), [])


class TestResolveVariants(unittest.TestCase):
    DECLARED = [
        {"id": "core", "name": "Core", "packages": ["gmscore", "vending"]},
        {"id": "basic", "name": "Basic", "includes": "core", "packages": ["dialer"]},
        {"id": "omni", "name": "Omni", "includes": "basic", "packages": ["gemini"]},
        {"id": "everything", "name": "Everything", "all": True},
    ]

    def shipped(self):
        # gemini does not exist before Android 15.
        return [pkg("gmscore"), pkg("vending"), pkg("dialer"), pkg("extra")]

    def test_tiers_accumulate(self):
        got = {v["id"]: v["packages"] for v in
               bm.resolve_variants(self.DECLARED, self.shipped())}
        self.assertEqual(got["core"], ["gmscore", "vending"])
        self.assertEqual(got["basic"], ["gmscore", "vending", "dialer"])

    def test_members_the_release_lacks_are_filtered_out(self):
        got = {v["id"]: v["packages"] for v in
               bm.resolve_variants(self.DECLARED, self.shipped())}
        self.assertNotIn("gemini", got["omni"])
        self.assertEqual(got["omni"], ["gmscore", "vending", "dialer"])

    def test_all_takes_everything_in_manifest_order(self):
        got = {v["id"]: v["packages"] for v in
               bm.resolve_variants(self.DECLARED, self.shipped())}
        self.assertEqual(got["everything"],
                         ["gmscore", "vending", "dialer", "extra"])

    def test_packages_come_back_in_manifest_order(self):
        # The picker shows them in manifest order, so the variant must agree.
        declared = [{"id": "v", "name": "V", "packages": ["dialer", "gmscore"]}]
        got = bm.resolve_variants(declared, self.shipped())
        self.assertEqual(got[0]["packages"], ["gmscore", "dialer"])

    def test_a_cycle_is_refused_rather_than_hanging(self):
        declared = [{"id": "a", "name": "A", "includes": "b"},
                    {"id": "b", "name": "B", "includes": "a"}]
        with self.assertRaises(SystemExit):
            bm.resolve_variants(declared, self.shipped())

    def test_including_something_that_does_not_exist_is_refused(self):
        declared = [{"id": "a", "name": "A", "includes": "nope"}]
        with self.assertRaises(SystemExit):
            bm.resolve_variants(declared, self.shipped())


class TestCheckStubs(unittest.TestCase):
    def test_a_package_shipping_only_a_stub_is_refused(self):
        # A stub without the app it stands in for leaves a dead system entry.
        pkgs = [{"id": "themes", "files": [
            {"path": "product/app/Themes/ThemesStub.apk", "stub": True}]}]
        self.assertEqual(len(bm.check_stubs(pkgs)), 1)

    def test_a_stub_beside_its_counterpart_is_fine(self):
        pkgs = [{"id": "chrome", "files": [
            {"path": "product/app/Chrome-Stub/Chrome-Stub.apk", "stub": True},
            {"path": "product/app/Chrome/Chrome.apk"}]}]
        self.assertEqual(bm.check_stubs(pkgs), [])


if __name__ == "__main__":
    unittest.main()


class TestPublishAsset(unittest.TestCase):
    """GitHub serves assets uncompressed, so the saving has to happen here."""

    def setUp(self):
        import tempfile, pathlib
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.assets = self.dir / "assets"
        self.assets.mkdir()

    def write(self, name, data):
        p = self.dir / name
        p.write_bytes(data)
        return p, *bm.sha256_of(p)

    def test_compressible_payload_is_published_compressed(self):
        src, digest, size = self.write("big.apk", b"A" * 200_000)
        e = bm.publish_asset(src, digest, size, "product/app/X/X.apk", self.assets)
        self.assertEqual(e["encoding"], "gzip")
        self.assertTrue(e["asset"].endswith(".gz"))
        self.assertLess(e["asset_size"], size)
        # The file's own digest and size still describe what gets installed.
        self.assertEqual(e["sha256"], digest)
        self.assertEqual(e["size"], size)

    def test_the_artifact_digest_matches_the_artifact(self):
        src, digest, size = self.write("big.apk", b"B" * 200_000)
        e = bm.publish_asset(src, digest, size, "product/app/X/X.apk", self.assets)
        got = bm.sha256_of(self.assets / e["asset"])
        self.assertEqual(got, (e["asset_sha256"], e["asset_size"]))

    def test_the_artifact_decompresses_back_to_the_original(self):
        import gzip as gz
        data = bytes(range(256)) * 900
        src, digest, size = self.write("x.apk", data)
        e = bm.publish_asset(src, digest, size, "product/app/X/X.apk", self.assets)
        self.assertEqual(gz.decompress((self.assets / e["asset"]).read_bytes()), data)

    def test_incompressible_payload_is_published_as_is(self):
        # Random bytes stand in for an already-compressed artifact.
        import os as _os
        src, digest, size = self.write("r.apk", _os.urandom(200_000))
        e = bm.publish_asset(src, digest, size, "product/app/X/X.apk", self.assets)
        self.assertNotIn("encoding", e)
        self.assertFalse(e["asset"].endswith(".gz"))
        self.assertTrue((self.assets / e["asset"]).exists())
        # And the rejected attempt is not left lying in the release.
        self.assertEqual(list(self.assets.glob("*.gz")), [])

    def test_compression_is_deterministic(self):
        # A gzip header timestamp would change the digest on every run.
        src, digest, size = self.write("d.apk", b"C" * 200_000)
        first = bm.publish_asset(src, digest, size, "product/app/X/X.apk", self.assets)
        for f in self.assets.iterdir():
            f.unlink()
        second = bm.publish_asset(src, digest, size, "product/app/X/X.apk", self.assets)
        self.assertEqual(first["asset_sha256"], second["asset_sha256"])


class TestPrivappAllowlists(unittest.TestCase):
    """A privileged app with no allowlist entry bootloops the device."""

    def setUp(self):
        import tempfile, pathlib
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "product/etc/permissions").mkdir(parents=True)
        (self.root / "product/etc/permissions/privapp-permissions-google.xml").write_text(
            '<permissions>\n'
            '  <privapp-permissions package="com.google.android.gms">\n'
            '    <permission name="android.permission.INSTALL_PACKAGES"/>\n'
            '  </privapp-permissions>\n'
            '</permissions>\n')
        # An apk that will not parse goes unreported rather than crashing.
        self.real_read = bm.read_package_id
        bm.read_package_id = lambda root, rel: {
            "product/priv-app/PrebuiltGmsCore/PrebuiltGmsCore.apk": "com.google.android.gms",
            "system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk":
                "com.google.android.gsf",
        }.get(rel)

    def tearDown(self):
        bm.read_package_id = self.real_read

    def pkgs(self, *paths):
        return [{"id": "core", "files": [{"path": p} for p in paths]}]

    def test_allowlisted_privapp_is_fine(self):
        got = bm.check_privapp_allowlists(self.root, self.pkgs(
            "product/etc/permissions/privapp-permissions-google.xml",
            "product/priv-app/PrebuiltGmsCore/PrebuiltGmsCore.apk"))
        self.assertEqual(got, [])

    def test_unallowlisted_privapp_is_reported(self):
        # GoogleServicesFramework's allowlist is in system_ext, which the
        # definitions did not glob: this is the bootloop that happened.
        got = bm.check_privapp_allowlists(self.root, self.pkgs(
            "product/etc/permissions/privapp-permissions-google.xml",
            "system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk"))
        self.assertEqual(len(got), 1)
        self.assertIn("com.google.android.gsf", got[0])

    def test_shipping_the_missing_allowlist_settles_it(self):
        (self.root / "system_ext/etc/permissions").mkdir(parents=True)
        (self.root / "system_ext/etc/permissions/privapp-permissions-google-se.xml").write_text(
            '<permissions><privapp-permissions package="com.google.android.gsf">'
            '<permission name="android.permission.INSTALL_LOCATION_PROVIDER"/>'
            '</privapp-permissions></permissions>')
        got = bm.check_privapp_allowlists(self.root, self.pkgs(
            "system_ext/etc/permissions/privapp-permissions-google-se.xml",
            "system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk"))
        self.assertEqual(got, [])

    def test_chimera_modules_are_not_scanned_by_packagemanager(self):
        got = bm.check_privapp_allowlists(self.root, self.pkgs(
            "product/priv-app/PrebuiltGmsCore/app_chimera/m/X/X.apk",
            "product/priv-app/PrebuiltGmsCore/m/optional/Y.apk"))
        self.assertEqual(got, [])


class TestPixelThemesStubs(unittest.TestCase):
    """a13-a15 images carry two Pixel Themes stubs.

    Both declare com.google.android.apps.customization.pixel at versionCode 2,
    so PackageManager installs one and logs the other as a duplicate. The two
    differ only in three legacy icon bundles, which PixelThemesStub has and
    PixelThemesStub2022_and_newer does not, so we ship the first and record
    the second as deliberately dropped.
    """

    def defs(self, rel):
        import yaml
        return yaml.safe_load(open(Path(__file__).parent.parent
                                   / "packages" / f"{rel}.yaml"))

    def test_only_one_stub_is_claimed(self):
        files = ["product/app/PixelThemesStub/PixelThemesStub.apk",
                 "product/app/PixelThemesStub2022_and_newer/"
                 "PixelThemesStub2022_and_newer.apk"]
        for rel in ("a13", "a14", "a15"):
            doc = self.defs(rel)
            by_package, unclaimed = bm.assign(files, doc["packages"])
            self.assertEqual(by_package["pixelthemes"], files[:1], rel)
            self.assertEqual(unclaimed, files[1:], rel)

    def test_the_dropped_stub_is_not_reported_as_missed(self):
        for rel in ("a13", "a14", "a15"):
            doc = self.defs(rel)
            left = bm.drop_excluded(
                ["product/app/PixelThemesStub2022_and_newer/"
                 "PixelThemesStub2022_and_newer.apk"], doc["exclude"])
            self.assertEqual(left, [], rel)

    def test_later_releases_ship_their_one_stub(self):
        for rel, name in (("a16", "PixelThemesStub2025"),
                          ("a17", "PixelThemesStub2026")):
            doc = self.defs(rel)
            path = f"product/app/{name}/{name}.apk"
            by_package, unclaimed = bm.assign([path], doc["packages"])
            self.assertEqual(by_package["pixelthemes"], [path], rel)
            self.assertEqual(unclaimed, [], rel)
