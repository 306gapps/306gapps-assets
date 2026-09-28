import unittest

import prune_stale


def rel(rid, api, created, device="x"):
    return {"id": rid, "android": {"api": api, "version": str(api - 20)},
            "device": device, "build": rid.upper(), "created": created}


class TestStale(unittest.TestCase):
    def test_keeps_the_newest_per_android_version(self):
        idx = {"releases": [
            rel("a15-old", 35, "2026-01-01"),
            rel("a15-new", 35, "2026-06-01"),
            rel("a17-only", 37, "2026-03-01"),
        ]}
        got = [r["id"] for r in prune_stale.stale(idx)]
        self.assertEqual(got, ["a15-old"])

    def test_nothing_stale_when_one_each(self):
        idx = {"releases": [rel("a16", 36, "2026-01-01"), rel("a17", 37, "2026-01-01")]}
        self.assertEqual(prune_stale.stale(idx), [])

    def test_three_of_a_version_leaves_only_the_newest(self):
        idx = {"releases": [
            rel("a15-a", 35, "2026-01-01"),
            rel("a15-b", 35, "2026-02-01"),
            rel("a15-c", 35, "2026-03-01"),
        ]}
        got = sorted(r["id"] for r in prune_stale.stale(idx))
        self.assertEqual(got, ["a15-a", "a15-b"])

    def test_empty_index(self):
        self.assertEqual(prune_stale.stale({}), [])


if __name__ == "__main__":
    unittest.main()
