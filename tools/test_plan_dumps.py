import json
import tempfile
import unittest
from pathlib import Path

from plan_dumps import published, supported_versions

PAGE_DEFS = """android:
  api: {api}
  version: "{v}"
packages: []
"""


class TestSupportWindow(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, api=33, v="13"):
        (self.dir / name).write_text(PAGE_DEFS.format(api=api, v=v))

    def test_window_is_defined_by_the_definition_files(self):
        for n, (api, v) in {"a13.yaml": (33, "13"), "a15.yaml": (35, "15"),
                            "a17.yaml": (37, "17")}.items():
            self.write(n, api, v)
        self.assertEqual(sorted(supported_versions(self.dir)), [13, 15, 17])

    def test_ignores_files_that_are_not_version_definitions(self):
        self.write("a13.yaml")
        (self.dir / "README.yaml").write_text("x: 1\n")
        (self.dir / "a.yaml").write_text("x: 1\n")
        (self.dir / "abc.yaml").write_text("x: 1\n")
        self.assertEqual(list(supported_versions(self.dir)), [13])

    def test_empty_directory(self):
        self.assertEqual(supported_versions(self.dir), {})


class TestPublished(unittest.TestCase):
    def test_reads_release_ids(self):
        p = Path(tempfile.mkdtemp()) / "index.json"
        p.write_text(json.dumps({"schema": 1, "releases": [
            {"id": "a17-x"}, {"id": "a16-y"}]}))
        self.assertEqual(published(p), {"a17-x", "a16-y"})

    def test_missing_index_is_not_an_error(self):
        self.assertEqual(published(Path("/nonexistent/index.json")), set())

    def test_index_without_releases(self):
        p = Path(tempfile.mkdtemp()) / "index.json"
        p.write_text(json.dumps({"schema": 1}))
        self.assertEqual(published(p), set())


if __name__ == "__main__":
    unittest.main()
