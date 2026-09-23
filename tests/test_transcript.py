"""Test transcript: VTT parse + cache-first get_segments (Fase 4). Tanpa network."""

import os
import tempfile
import unittest
from unittest import mock

from cs_core import cache, transcript

VTT = """WEBVTT

00:00:01.000 --> 00:00:02.000
<c>cegukan</c>

00:00:01.000 --> 00:00:02.000
<00:00:01.000>cegukan lagi ya

00:00:05.000 --> 00:00:06.000
hiccup

00:00:03.000 --> 00:00:04.000
jegukan
"""


class TestVttParse(unittest.TestCase):
    def test_collapse_longest_and_sort(self):
        segs = transcript.parse_vtt_text(VTT)
        self.assertEqual([s["sec"] for s in segs], [1, 3, 5])
        # timestamp 1 punya dua cue -> ambil teks terpanjang, tag dibuang
        self.assertEqual(segs[0]["text"], "cegukan lagi ya")
        self.assertEqual(segs[1]["text"], "jegukan")
        self.assertEqual(segs[2]["text"], "hiccup")

    def test_empty(self):
        self.assertEqual(transcript.parse_vtt_text("WEBVTT\n\n"), [])


class TestNormalize(unittest.TestCase):
    def test_start_to_sec(self):
        raw = [{"text": "a", "start": 1.9, "duration": 2},
               {"text": "b", "start": 3.0, "duration": 1}]
        self.assertEqual(transcript._normalize_segments(raw),
                         [{"sec": 1, "text": "a"}, {"sec": 3, "text": "b"}])

    def test_sec_passthrough(self):
        raw = [{"sec": 5, "text": "hi"}]
        self.assertEqual(transcript._normalize_segments(raw), [{"sec": 5, "text": "hi"}])

    def test_blank_text_dropped(self):
        self.assertEqual(
            transcript._normalize_segments([{"sec": 1, "text": "  "}]),
            [])


class TestGetSegmentsCacheFirst(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_cache_hit_no_fetch(self):
        segs = [{"sec": 0, "text": "cegukan"}, {"sec": 9, "text": "hiccup"}]
        cache.write("vid1", "id", segs, source="yt-api", root=self.root)

        def _boom(*a, **k):
            raise AssertionError("fetch dipanggil padahal cache hit")

        with mock.patch.object(transcript, "fetch_api", _boom), \
             mock.patch.object(transcript, "fetch_vtt", _boom):
            out, source, status = transcript.get_segments(
                "vid1", "id", use_cache=True, root=self.root)
        self.assertEqual(status, "hit")
        self.assertEqual(source, "yt-api")
        self.assertEqual(out, segs)

    def test_use_cache_false_is_disabled(self):
        called = {"n": 0}

        def _fake(vid, lang):
            called["n"] += 1
            return [{"sec": 1, "text": "x"}], "yt-api"

        with mock.patch.object(transcript, "fetch_api", _fake):
            out, source, status = transcript.get_segments(
                "vid2", "id", use_cache=False, root=self.root)
        self.assertEqual(status, "disabled")
        self.assertEqual(called["n"], 1)
        self.assertEqual(out, [{"sec": 1, "text": "x"}])

    def test_miss_fetches_and_writes(self):
        with mock.patch.object(
            transcript, "fetch_api",
            lambda vid, lang: ([{"sec": 2, "text": "y"}], "yt-api"),
        ):
            out, source, status = transcript.get_segments(
                "vid3", "id", use_cache=True, root=self.root)
        self.assertEqual(status, "miss")
        self.assertIsNotNone(cache.read("vid3", "id", root=self.root))


class TestTranscriptLangs(unittest.TestCase):
    def test_te_map_p9(self):
        self.assertEqual(transcript.TRANSCRIPT_LANGS["te"], ["te", "te-IN", "hi"])

    def test_unknown_default(self):
        self.assertEqual(transcript.transcript_langs("xx"), ["id", "en", "id-ID"])


if __name__ == "__main__":
    unittest.main()
