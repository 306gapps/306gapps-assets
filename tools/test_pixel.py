import unittest

from pixel import Build, newest, parse

PAGE = """
<h2 id="legal" tabindex="-1">Legal</h2>
<h2 id="cubs" data-text='"cubs" for Pixel 11' tabindex="-1">"cubs" for Pixel 11</h2>
<table>
  <tr id="a"><td>17.0.0 (CD1A.260618.001.A7, Aug 2026)</td>
    <td><a href="https://dl.google.com/x/cubs-a7.zip">Link</a></td>
    <td>""" + "a"*64 + """</td></tr>
  <tr id="b"><td>17.0.0 (CD1A.260905.001.B1, Sep 2026)</td>
    <td><a href="https://dl.google.com/x/cubs-b1.zip">Link</a></td>
    <td>""" + "b"*64 + """</td></tr>
  <tr id="c"><td>17.0.0 (CD1A.260905.001.C9, Sep 2026, Verizon)</td>
    <td><a href="https://dl.google.com/x/cubs-c9.zip">Link</a></td>
    <td>""" + "c"*64 + """</td></tr>
</table>
<h2 id="comet" data-text='"comet" for Pixel 9 Pro Fold' tabindex="-1">"comet" for Pixel 9 Pro Fold</h2>
<table>
  <tr id="d"><td>17.0.0 (CD1A.260905.001.B1, Sep 2026)</td>
    <td><a href="https://dl.google.com/x/comet-b1.zip">Link</a></td>
    <td>""" + "d"*64 + """</td></tr>
  <tr id="e"><td>16.0.0 (BP41.250901.001, Sep 2025)</td>
    <td><a href="https://dl.google.com/x/comet-old.zip">Link</a></td>
    <td>""" + "e"*64 + """</td></tr>
</table>
"""


class TestParse(unittest.TestCase):
    def setUp(self):
        self.builds = parse(PAGE)

    def test_parses_every_row(self):
        self.assertEqual(len(self.builds), 5)

    def test_reads_codename_and_model(self):
        b = self.builds[0]
        self.assertEqual(b.device, "cubs")
        self.assertEqual(b.model, "Pixel 11")
        self.assertEqual(b.build_id, "CD1A.260618.001.A7")
        self.assertEqual(b.month, "Aug 2026")

    def test_rows_are_attributed_to_the_right_device(self):
        self.assertEqual({b.device for b in self.builds[:3]}, {"cubs"})
        self.assertEqual({b.device for b in self.builds[3:]}, {"comet"})

    def test_carrier_builds_are_flagged(self):
        carrier = [b for b in self.builds if not b.generic]
        self.assertEqual(len(carrier), 1)
        self.assertEqual(carrier[0].carrier, "Verizon")

    def test_legal_heading_is_not_a_device(self):
        self.assertNotIn("legal", {b.device for b in self.builds})


class TestNewest(unittest.TestCase):
    def setUp(self):
        self.builds = parse(PAGE)

    def test_prefers_the_device_listed_first(self):
        b = newest(self.builds)
        self.assertEqual(b.device, "cubs")

    def test_skips_carrier_builds(self):
        self.assertEqual(newest(self.builds).build_id, "CD1A.260905.001.B1")

    def test_honours_an_explicit_device(self):
        self.assertEqual(newest(self.builds, device="comet").device, "comet")

    def test_honours_an_explicit_major_version(self):
        b = newest(self.builds, device="comet", major=16)
        self.assertEqual(b.build_id, "BP41.250901.001")

    def test_returns_none_when_nothing_matches(self):
        self.assertIsNone(newest(self.builds, device="nosuchdevice"))
        self.assertIsNone(newest(self.builds, major=99))

    def test_sort_key_orders_by_version_then_date(self):
        old = Build("x", "X", "16.0.0", "A", "Dec 2025", "", "")
        new = Build("x", "X", "17.0.0", "A", "Jan 2026", "", "")
        self.assertLess(old.sort_key(), new.sort_key())
        jan = Build("x", "X", "17.0.0", "A", "Jan 2026", "", "")
        sep = Build("x", "X", "17.0.0", "A", "Sep 2026", "", "")
        self.assertLess(jan.sort_key(), sep.sort_key())

    def test_empty_input(self):
        self.assertIsNone(newest([]))


if __name__ == "__main__":
    unittest.main()
