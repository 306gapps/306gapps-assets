import unittest

from globmatch import matches


class TestGlob(unittest.TestCase):
    def test_star_does_not_cross_separator(self):
        self.assertTrue(matches("product/app/*", "product/app/Photos"))
        self.assertFalse(matches("product/app/*", "product/app/Photos/Photos.apk"))

    def test_doublestar_crosses_separators(self):
        self.assertTrue(matches("product/app/Photos/**", "product/app/Photos/Photos.apk"))
        self.assertTrue(matches("product/app/Photos/**", "product/app/Photos/lib/arm64/libx.so"))

    def test_trailing_doublestar_matches_the_directory_itself(self):
        self.assertTrue(matches("product/app/Photos/**", "product/app/Photos"))

    def test_doublestar_does_not_leak_to_siblings(self):
        self.assertFalse(matches("product/app/Photos/**", "product/app/PhotosOther/x.apk"))

    def test_exact_path(self):
        self.assertTrue(matches("product/etc/sysconfig/google.xml", "product/etc/sysconfig/google.xml"))
        self.assertFalse(matches("product/etc/sysconfig/google.xml", "product/etc/sysconfig/google2.xml"))

    def test_partial_star_in_name(self):
        self.assertTrue(matches("product/priv-app/EuiccGoogle*/**", "product/priv-app/EuiccGoogleUx/E.apk"))
        self.assertFalse(matches("product/priv-app/EuiccGoogle*/**", "product/priv-app/Euicc/E.apk"))

    def test_question_mark(self):
        self.assertTrue(matches("product/app/A?.apk", "product/app/Ab.apk"))
        self.assertFalse(matches("product/app/A?.apk", "product/app/Abc.apk"))

    def test_character_class(self):
        self.assertTrue(matches("product/app/lib[0-9].so", "product/app/lib3.so"))
        self.assertFalse(matches("product/app/lib[0-9].so", "product/app/libx.so"))

    def test_regex_metacharacters_are_literal(self):
        self.assertTrue(matches("product/app/A+B/x.apk", "product/app/A+B/x.apk"))
        self.assertFalse(matches("product/app/A+B/x.apk", "product/app/AAB/x.apk"))


if __name__ == "__main__":
    unittest.main()


class TestIgnoreRules(unittest.TestCase):
    """The dump-wide ignore list, which decides what never reaches a package."""

    def ignored(self, path: str) -> bool:
        from build_manifest import IGNORE
        return any(matches(i, path) for i in IGNORE)

    def test_drops_ahead_of_time_artifacts(self):
        # Bound to the boot classpath they were compiled against, so useless on
        # any custom ROM and wrong for a ROM build's own dexpreopt.
        for p in ("product/priv-app/GmsCore/oat/arm64/GmsCore.odex",
                  "product/priv-app/GmsCore/oat/arm64/GmsCore.vdex",
                  "product/app/Photos/oat/arm/Photos.odex",
                  "system/framework/arm64/boot.art"):
            self.assertTrue(self.ignored(p), p)

    def test_keeps_the_payloads_that_matter(self):
        for p in ("product/priv-app/GmsCore/GmsCore.apk",
                  "product/apex/com.google.android.gmssystem.apex",
                  "product/etc/permissions/privapp-permissions-google.xml",
                  "product/framework/com.google.android.dialer.support.jar"):
            self.assertFalse(self.ignored(p), p)

    def test_drops_rom_metadata(self):
        for p in ("product/etc/build.prop", "product/etc/selinux/x_file_contexts"):
            self.assertTrue(self.ignored(p), p)
