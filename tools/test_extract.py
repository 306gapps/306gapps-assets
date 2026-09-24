import unittest
import tempfile
from pathlib import Path

from extract import drop, image_format, EROFS_MAGIC, EXT4_MAGIC
import struct


class TestDrop(unittest.TestCase):
    def test_removes_the_file(self):
        d = Path(tempfile.mkdtemp())
        f = d / "big.img"
        f.write_bytes(b"x" * 1024)
        drop(f)
        self.assertFalse(f.exists())

    def test_missing_file_is_not_an_error(self):
        drop(Path("/nonexistent/nothing.img"))

    def test_directory_is_left_alone(self):
        d = Path(tempfile.mkdtemp())
        drop(d)
        self.assertTrue(d.exists())


class TestImageFormat(unittest.TestCase):
    def img(self, writer) -> Path:
        p = Path(tempfile.mkdtemp()) / "p.img"
        buf = bytearray(2048)
        writer(buf)
        p.write_bytes(bytes(buf))
        return p

    def test_detects_erofs(self):
        def w(buf):
            buf[1024:1028] = struct.pack("<I", EROFS_MAGIC)
        self.assertEqual(image_format(self.img(w)), "erofs")

    def test_detects_ext4(self):
        def w(buf):
            buf[1024 + 56:1024 + 58] = struct.pack("<H", EXT4_MAGIC)
        self.assertEqual(image_format(self.img(w)), "ext4")

    def test_unknown_is_reported_not_guessed(self):
        self.assertEqual(image_format(self.img(lambda b: None)), "unknown")

    def test_truncated_image(self):
        p = Path(tempfile.mkdtemp()) / "t.img"
        p.write_bytes(b"\x00" * 100)
        self.assertEqual(image_format(p), "unknown")


if __name__ == "__main__":
    unittest.main()
