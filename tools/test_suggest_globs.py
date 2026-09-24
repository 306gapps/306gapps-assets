import unittest

from suggest_globs import core, directories, stem


class TestStem(unittest.TestCase):
    def test_takes_the_directory_a_glob_targets(self):
        self.assertEqual(stem("product/priv-app/Velvet/**"), "Velvet")
        self.assertEqual(stem("product/app/FindMyDevicePrebuilt-*/**"),
                         "FindMyDevicePrebuilt-")

    def test_strips_file_extensions(self):
        self.assertEqual(stem("product/etc/permissions/com.google.x.xml"),
                         "com.google.x")


class TestCore(unittest.TestCase):
    """Matching on words shared by half the dump pairs unrelated apps."""

    def test_strips_common_words(self):
        self.assertEqual(core("GoogleKeepPrebuilt"), "Keep")
        self.assertEqual(core("NexusLauncherRelease"), "NexusLauncher")

    def test_strips_version_suffixes(self):
        self.assertEqual(core("RecorderPrebuilt_847964105"), "Recorder")
        self.assertEqual(core("FamilySpacePrebuilt-v484"), "FamilySpace")

    def test_keeps_the_distinctive_part(self):
        self.assertIn("Velvet", core("Velvet"))
        self.assertEqual(core("PrebuiltBugle"), "Bugle")

    def test_unrelated_apps_do_not_collapse_together(self):
        # Both end in Prebuilt; only the distinctive part should survive.
        self.assertNotEqual(core("GoogleKeepPrebuilt"), core("FilesPrebuilt"))


class TestDirectories(unittest.TestCase):
    def test_indexes_app_directories(self):
        d = directories([
            "product/priv-app/Velvet/Velvet.apk",
            "product/app/Photos/Photos.apk",
            "system_ext/priv-app/SettingsGoogle/x.apk",
            "product/etc/permissions/foo.xml",
        ])
        self.assertEqual(d["Velvet"], "product/priv-app/Velvet")
        self.assertEqual(d["Photos"], "product/app/Photos")
        self.assertIn("SettingsGoogle", d)
        self.assertNotIn("permissions", d)


if __name__ == "__main__":
    unittest.main()
