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


class TestErofsVersionGuard(unittest.TestCase):
    """The guard exists because erofs-utils 1.7.1 truncates large files and
    still exits zero."""

    def test_parses_the_reported_version(self):
        import extract
        real = extract.subprocess.run

        def fake(cmd, **kw):
            class R:
                stdout = ("fsck.erofs (erofs-utils) 1.9.4\n"
                          "available decompressors: lz4, lzma\n")
            return R()

        extract.subprocess.run = fake
        try:
            self.assertEqual(extract.erofs_version("fsck.erofs"), (1, 9, 4))
        finally:
            extract.subprocess.run = real

    def test_rejects_a_version_known_to_corrupt(self):
        import extract
        real = extract.erofs_version
        extract.erofs_version = lambda _: (1, 7, 1)
        try:
            with self.assertRaises(SystemExit) as cm:
                extract.check_erofs("fsck.erofs")
            self.assertIn("1.7.1", str(cm.exception))
        finally:
            extract.erofs_version = real

    def test_accepts_a_good_version(self):
        import extract
        real = extract.erofs_version
        extract.erofs_version = lambda _: (1, 8, 0)
        try:
            extract.check_erofs("fsck.erofs")
        finally:
            extract.erofs_version = real

    def test_unreadable_version_warns_rather_than_blocks(self):
        import extract
        real = extract.erofs_version
        extract.erofs_version = lambda _: None
        try:
            extract.check_erofs("fsck.erofs")
        finally:
            extract.erofs_version = real
