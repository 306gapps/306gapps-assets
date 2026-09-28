import unittest

import build_manifest as bm


def pkg(pid, **kw):
    return {"id": pid, "files": [], **kw}


class TestPruneConflicts(unittest.TestCase):
    """The definitions cover every Android version; a release ships a subset."""

    def test_conflict_with_a_package_the_release_lacks_is_dropped(self):
        # com.google.android.verifier only exists from Android 16, so on older
        # releases the blocker's conflict points at nothing. That is satisfied
        # by definition, not a broken manifest.
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
