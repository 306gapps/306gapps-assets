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
