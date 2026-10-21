"""Test pencarian (index rekursif + cache transkrip) dan penamaan laporan."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from cs_core import cache, reports, search
from cs_core.video import parse_video_id, video_url

class TestVideoId(unittest.TestCase):
    def test_accepts_common_url_shapes(self):
        for raw in (
            "gAQIEyzUHYc",
            "https://youtu.be/gAQIEyzUHYc",
            "https://youtu.be/gAQIEyzUHYc?t=42",
            "https://www.youtube.com/watch?v=gAQIEyzUHYc",
            "https://www.youtube.com/watch?v=gAQIEyzUHYc&list=PLx",
            "https://m.youtube.com/watch?v=gAQIEyzUHYc&feature=share",
            "https://www.youtube.com/shorts/gAQIEyzUHYc",
            "https://www.youtube.com/embed/gAQIEyzUHYc",
            "https://www.youtube.com/live/gAQIEyzUHYc",
            "youtube.com/watch?v=gAQIEyzUHYc",
            "  gAQIEyzUHYc  ",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_video_id(raw), "gAQIEyzUHYc")

    def test_rejects_non_ids(self):
        for raw in ("", "bukan-id", "https://youtu.be/short", "abc"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_video_id(raw), "")

    def test_url_includes_timestamp(self):
        self.assertEqual(video_url("gAQIEyzUHYc"), "https://youtu.be/gAQIEyzUHYc")
        self.assertEqual(video_url("gAQIEyzUHYc", 0), "https://youtu.be/gAQIEyzUHYc")
        self.assertEqual(video_url("gAQIEyzUHYc", 90), "https://youtu.be/gAQIEyzUHYc?t=90")

class TestSearchQuery(unittest.TestCase):
    def test_or_between_clauses_and_and_inside(self):
        groups = search.parse_query('"lagi minum" OR cegukan AND minum')
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]), 1)
        self.assertEqual(len(groups[1]), 2)

    def test_single_letter_terms_ignored(self):
        groups = search.parse_query("a cegukan")
        self.assertEqual(len(groups[0]), 1)
        self.assertEqual(groups[0][0].pattern, "cegukan")

class _TempIndex(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_index(self, rel: str, video_id: str, segments, lang="id", status="ok"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "status": status, "video_id": video_id, "lang": lang,
            "segments": segments,
        }), encoding="utf-8")
        return path

class TestIndexSearch(_TempIndex):
    def test_finds_files_in_nested_batch_layout(self):
        """Index Mode menulis ke `{channel}/batch_NN/index/` — dulu 0 hasil."""
        self._write_index("chA/batch_01/index/vid1.json", "vid1", [
            {"sec": 0, "text": "aku cegukan terus"},
            {"sec": 300, "text": "cegukan lagi"},
        ])
        results = search.search_index(self.root, "cegukan")
        self.assertEqual([r.video_id for r in results], ["vid1"])
        self.assertEqual(results[0].hit_count, 2)
        self.assertEqual(results[0].channel, "chA")
        # `?t=` hanya untuk detik > 0 supaya link tidak kotor.
        self.assertEqual(results[0].hits[0].url, "https://youtu.be/vid1")
        self.assertEqual(results[0].hits[1].url, "https://youtu.be/vid1?t=300")

    def test_flat_layout_still_works(self):
        self._write_index("vid1.json", "vid1", [{"sec": 5, "text": "cegukan"}])
        self.assertEqual(len(search.search_index(self.root, "cegukan")), 1)

    def test_ignores_meta_and_status_files(self):
        self._write_index("chA/batch_01/index/meta.json", "", [{"sec": 0, "text": "cegukan"}])
        self._write_index("chA/batch_01/index/vid1.json", "vid1", [{"sec": 0, "text": "cegukan"}])
        results = search.search_index(self.root, "cegukan")
        self.assertEqual([r.video_id for r in results], ["vid1"])

    def test_skips_failed_status(self):
        self._write_index("chA/batch_01/index/vid1.json", "vid1",
                          [{"sec": 0, "text": "cegukan"}], status="no_transcript")
        self.assertEqual(search.search_index(self.root, "cegukan"), [])

    def test_and_requires_all_terms_in_same_video(self):
        self._write_index("a/vid1.json", "vid1", [{"sec": 0, "text": "cegukan minum"}])
        self._write_index("a/vid2.json", "vid2", [{"sec": 0, "text": "cegukan saja"}])
        results = search.search_index(self.root, "cegukan AND minum")
        self.assertEqual([r.video_id for r in results], ["vid1"])

    def test_or_matches_either(self):
        self._write_index("a/vid1.json", "vid1", [{"sec": 0, "text": "cegukan"}])
        self._write_index("a/vid2.json", "vid2", [{"sec": 0, "text": "hiccups"}])
        results = search.search_index(self.root, "cegukan OR hiccups")
        self.assertEqual(len(results), 2)

    def test_hits_dedup_by_timestamp(self):
        self._write_index("a/vid1.json", "vid1", [
            {"sec": 10, "text": "cegukan"},
            {"sec": 10, "text": "cegukan lagi"},
        ])
        results = search.search_index(self.root, "cegukan")
        self.assertEqual(results[0].hit_count, 1)

    def test_channel_from_flat_layout(self):
        """Tata letak `{root}/{channel}/{video}.json` -> channel, bukan nama tmpdir."""
        self._write_index("chA/vid1.json", "vid1", [{"sec": 0, "text": "cegukan"}])
        results = search.search_index(self.root, "cegukan")
        self.assertEqual(results[0].channel, "chA")

    def test_channel_filter_actually_filters(self):
        self._write_index("chA/batch_01/index/vid1.json", "vid1",
                          [{"sec": 0, "text": "cegukan"}])
        self._write_index("chB/batch_01/index/vid2.json", "vid2",
                          [{"sec": 0, "text": "cegukan"}])
        self.assertEqual(len(search.search_index(self.root, "cegukan")), 2)
        filtered = search.search_index(self.root, "cegukan", "chA")
        self.assertEqual([r.video_id for r in filtered], ["vid1"])

    def test_channel_filter_accepts_at_prefix(self):
        self._write_index("chA/batch_01/index/vid1.json", "vid1",
                          [{"sec": 0, "text": "cegukan"}])
        self.assertEqual(len(search.search_index(self.root, "cegukan", "@chA")), 1)

    def test_channel_filter_excludes_unknown_channel(self):
        """File di luar struktur channel tidak bisa dicocokkan -> dibuang."""
        self._write_index("vid1.json", "vid1", [{"sec": 0, "text": "cegukan"}])
        self.assertEqual(search.search_index(self.root, "cegukan", "chA"), [])

class TestCacheSearch(_TempIndex):
    def test_searches_transcript_cache(self):
        cache.write("gAQIEyzUHYc", "id",
                    [{"sec": 272, "text": "24 jam cegukan"}],
                    source="yt-api", root=str(self.root))
        results = search.search_cache(str(self.root), "cegukan")
        self.assertEqual([r.video_id for r in results], ["gAQIEyzUHYc"])
        self.assertEqual(results[0].source, "cache")
        self.assertEqual(results[0].lang, "id")
        self.assertEqual(results[0].hits[0].url, "https://youtu.be/gAQIEyzUHYc?t=272")

    def test_combined_prefers_index_over_cache(self):
        self._write_index("chA/batch_01/index/gAQIEyzUHYc.json", "gAQIEyzUHYc",
                          [{"sec": 1, "text": "cegukan dari index"}])
        cache.write("gAQIEyzUHYc", "id", [{"sec": 2, "text": "cegukan dari cache"}],
                    source="yt-api", root=str(self.root))
        results = search.search("cegukan", index_root=self.root,
                                cache_root=str(self.root))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "index")

    def test_combined_includes_both_sources(self):
        self._write_index("chA/batch_01/index/vid1.json", "vid1",
                          [{"sec": 1, "text": "cegukan"}])
        cache.write("vid2", "id", [{"sec": 2, "text": "cegukan"}],
                    source="yt-api", root=str(self.root))
        results = search.search("cegukan", index_root=self.root, cache_root=str(self.root))
        self.assertEqual({r.source for r in results}, {"index", "cache"})

class TestCacheMultiRoot(_TempIndex):
    def test_channel_persisted_and_filterable(self):
        """`channel` harus ditulis, kalau tidak filter purge/search selalu kosong."""
        cache.write("vid1", "id", [{"sec": 1, "text": "cegukan"}],
                    source="yt-api", root=str(self.root), channel="windahbasudara")
        meta = cache.read_meta(cache.cache_path("vid1", "id", root=str(self.root)))
        self.assertEqual(meta["channel"], "windahbasudara")
        self.assertEqual(
            cache.purge(channel="windahbasudara", all=True, root=str(self.root)), 1)

    def test_channel_filter_rejects_other_channel(self):
        cache.write("vid1", "id", [{"sec": 1, "text": "cegukan"}],
                    source="yt-api", root=str(self.root), channel="chA")
        self.assertEqual(cache.purge(channel="chB", all=True, root=str(self.root)), 0)
        self.assertIsNotNone(cache.read("vid1", "id", root=str(self.root)))

    def test_search_cache_respects_channel(self):
        cache.write("vid1", "id", [{"sec": 1, "text": "cegukan"}],
                    source="yt-api", root=str(self.root), channel="chA")
        self.assertEqual(len(search.search_cache(str(self.root), "cegukan", "chA")), 1)
        self.assertEqual(len(search.search_cache(str(self.root), "cegukan", "chB")), 0)

    def test_reads_cache_from_non_primary_root(self):
        """Cache lama di root lain tetap terbaca walau primer sudah pindah."""
        legacy = self.root / "legacy"
        cache.write("vid9", "id", [{"sec": 1, "text": "x"}],
                    source="yt-api", root=str(legacy))
        env = {"CS_DATA_DIR": str(self.root / "primary")}
        old = os.environ.get("CS_DATA_DIR")
        os.environ["CS_DATA_DIR"] = env["CS_DATA_DIR"]
        try:
            self.assertEqual(cache.cache_root().parent, self.root / "primary")
            # Root eksplisit tetap terisolasi.
            self.assertEqual(cache.read("vid9", "id", root=str(legacy)),
                             [{"sec": 1, "text": "x"}])
        finally:
            if old is None:
                os.environ.pop("CS_DATA_DIR", None)
            else:
                os.environ["CS_DATA_DIR"] = old

    def test_stats_lists_every_root(self):
        cache.write("a", "id", [{"sec": 1, "text": "x"}], source="t", root=str(self.root))
        data = cache.stats(str(self.root))
        self.assertEqual(data["files"], 1)
        self.assertEqual(len(data["roots"]), 1)
        self.assertTrue(data["roots"][0]["primary"])

    def test_recent_orders_by_mtime_and_dedups(self):
        cache.write("a", "id", [{"sec": 1, "text": "x"}], source="t", root=str(self.root))
        cache.write("b", "en", [{"sec": 1, "text": "x"}], source="t", root=str(self.root))
        rows = cache.recent(10, root=str(self.root))
        self.assertEqual({r["video_id"] for r in rows}, {"a", "b"})
        self.assertEqual(len(rows), 2)

class TestReportStore(_TempIndex):
    def test_naming_scheme(self):
        path = reports.report_path("windahbasudara",
                                   when=datetime(2026, 10, 3, 23, 50),
                                   folder=self.root)
        self.assertEqual(path.name, "laporan_windahbasudara_03102026_2350.html")

    def test_label_with_underscore_round_trips(self):
        path = reports.report_path("My_Channel",
                                   when=datetime(2026, 10, 3, 23, 50),
                                   folder=self.root)
        path.write_text("<html></html>", encoding="utf-8")
        items = reports.list_reports(self.root)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, "My_Channel")

    def test_list_is_newest_first(self):
        old = reports.report_path("a", when=datetime(2026, 1, 1, 0, 0), folder=self.root)
        new = reports.report_path("b", when=datetime(2026, 6, 1, 0, 0), folder=self.root)
        old.write_text("x", encoding="utf-8")
        new.write_text("x", encoding="utf-8")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        self.assertEqual([r.label for r in reports.list_reports(self.root)], ["b", "a"])

    def test_prune_keeps_newest(self):
        for i, name in enumerate(("a", "b", "c")):
            path = reports.report_path(name, when=datetime(2026, 1, 1, 0, i),
                                       folder=self.root)
            path.write_text("x", encoding="utf-8")
            os.utime(path, (1000 + i, 1000 + i))
        self.assertEqual(reports.prune(keep=1, folder=self.root), 2)
        self.assertEqual([r.label for r in reports.list_reports(self.root)], ["c"])

    def test_prune_zero_removes_all(self):
        path = reports.report_path("a", when=datetime(2026, 1, 1, 0, 0), folder=self.root)
        path.write_text("x", encoding="utf-8")
        self.assertEqual(reports.prune(keep=0, folder=self.root), 1)
        self.assertEqual(reports.list_reports(self.root), [])

    def test_ignores_non_report_files(self):
        (self.root / "catatan.html").write_text("x", encoding="utf-8")
        (self.root / "laporan_x.txt").write_text("x", encoding="utf-8")
        self.assertEqual(reports.list_reports(self.root), [])

if __name__ == "__main__":
    unittest.main()
