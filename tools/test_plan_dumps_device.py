import tempfile
import unittest
from pathlib import Path

import plan_dumps


class TestPreferredDevice(unittest.TestCase):
    """The a-series and base models omit hardware-gated apps, so each version
    pins the device it wants."""

    def write(self, body):
        d = Path(tempfile.mkdtemp()) / "a17.yaml"
        d.write_text(body)
        return d

    def test_reads_the_pinned_device(self):
        p = self.write("android:\n  api: 37\n  device: kodiak\n  version: '17'\n")
        self.assertEqual(plan_dumps.preferred_device(p), "kodiak")

    def test_no_pin_is_empty_not_an_error(self):
        p = self.write("android:\n  api: 37\n  version: '17'\n")
        self.assertEqual(plan_dumps.preferred_device(p), "")

    def test_unreadable_file_does_not_raise(self):
        self.assertEqual(plan_dumps.preferred_device(Path("/nope/a17.yaml")), "")

    def test_malformed_yaml_does_not_raise(self):
        p = self.write("android: [unclosed\n")
        self.assertEqual(plan_dumps.preferred_device(p), "")

    def test_every_shipped_definition_pins_a_device(self):
        # A version without a pin silently falls back to whatever Google lists
        # first, which is how we ended up dumping two a-series phones.
        for v in ("a13", "a14", "a15", "a16", "a17"):
            p = Path(__file__).parent.parent / "packages" / f"{v}.yaml"
            self.assertTrue(plan_dumps.preferred_device(p), f"{v} pins no device")


if __name__ == "__main__":
    unittest.main()
