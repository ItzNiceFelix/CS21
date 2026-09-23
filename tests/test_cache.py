"""Test cache transcript gzip JSONL (Fase 4). Tanpa network."""

import gzip
import os
import tempfile
import unittest

from cs_core import cache


class TestCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_roundtrip(self):
        segs = [{"sec": 0, "text": "cegukan"}, {"sec": 12, "text": "hiccup"}]
        path = cache.write("abc", "id", segs, source="yt-api", root=self.root)
        self.assertTrue(path.is_file())
        self.assertTrue(path.name.endswith(".abc.id.jsonl.gz") or path.name == "abc.id.jsonl.gz")
        self.assertEqual(cache.read("abc", "id", root=self.root), segs)

    def test_norm_lang(self):
        self.assertEqual(cache.norm_lang("id-ID"), "id")
        self.assertEqual(cache.norm_lang("EN-us"), "en")
        self.assertEqual(cache.norm_lang(""), "")

    def test_lang_alias_same_file(self):
        cache.write("abc", "id-ID", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        self.assertIsNotNone(cache.read("abc", "id", root=self.root))

    def test_ttl_zero_is_miss(self):
        cache.write("abc", "id", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        path = cache.cache_path("abc", "id", root=self.root)
        old = os.path.getmtime(path) - 40 * 86400
        os.utime(path, (old, old))
        self.assertIsNone(cache.read("abc", "id", root=self.root, ttl_days=0))
        self.assertEqual(cache.read("abc", "id", root=self.root, ttl_days=100),
                         [{"sec": 1, "text": "x"}])

    def test_format_version_mismatch_is_miss(self):
        path = cache.cache_path("abc", "id", root=self.root)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write('{"_meta":{"v":999,"id":"abc","lang":"id"}}\n')
            fh.write('{"seg":{"sec":1,"text":"x"}}\n')
        self.assertIsNone(cache.read("abc", "id", root=self.root))

    def test_no_tmp_left_behind(self):
        cache.write("abc", "id", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        leftovers = [p for p in os.listdir(cache.cache_root(self.root)) if p.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupt_middle_line_skipped(self):
        path = cache.cache_path("abc", "id", root=self.root)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write('{"_meta":{"v":1,"id":"abc","lang":"id"}}\n')
            fh.write('{"seg":{"sec":1,"text":"a"}}\n')
            fh.write("{ this is not json\n")
            fh.write('{"seg":{"sec":2,"text":"b"}}\n')
        self.assertEqual(cache.read("abc", "id", root=self.root),
                         [{"sec": 1, "text": "a"}, {"sec": 2, "text": "b"}])

    def test_missing_is_none(self):
        self.assertIsNone(cache.read("nope", "id", root=self.root))

    def test_purge_exact(self):
        cache.write("a", "id", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        cache.write("a", "en", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        cache.write("b", "id", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        self.assertEqual(cache.purge(video_id="a", lang="id", root=self.root), 1)
        self.assertIsNone(cache.read("a", "id", root=self.root))
        self.assertIsNotNone(cache.read("a", "en", root=self.root))
        self.assertIsNotNone(cache.read("b", "id", root=self.root))

    def test_purge_all(self):
        for vid in ("a", "b", "c"):
            cache.write(vid, "id", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        self.assertEqual(cache.purge(all=True, root=self.root), 3)
        self.assertEqual(os.listdir(cache.cache_root(self.root)), [])

    def test_gc_old(self):
        cache.write("a", "id", [{"sec": 1, "text": "x"}], source="yt-api", root=self.root)
        path = cache.cache_path("a", "id", root=self.root)
        old = os.path.getmtime(path) - 40 * 86400
        os.utime(path, (old, old))
        self.assertEqual(cache.gc(root=self.root, ttl_days=30), 1)
        self.assertIsNone(cache.read("a", "id", root=self.root))


if __name__ == "__main__":
    unittest.main()
