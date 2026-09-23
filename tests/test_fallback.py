"""Fase 3 — fallback RapidFuzz absen (arch §8, T3.5).

Monkeypatch `cs_core.diagnostics.HAVE_RAPIDFUZZ=False` dan pastikan
`cs_core.matching` membaca lewat helper `_has_rapidfuzz()` (patch terlihat),
hasil konsisten dengan jalur difflib.
"""

import unittest
from unittest import mock

from cs_core import diagnostics, matching
from cs_core.languages import load
from cs_core.scoring import score_segments


class TestFallbackStatus(unittest.TestCase):
    def test_status_shape(self):
        st = diagnostics.fallback_status()
        self.assertIn("rapidfuzz", st)
        self.assertIn("difflib", st)
        self.assertIn(st["engine"], ("rapidfuzz", "difflib"))
        self.assertEqual(st["degraded"], not st["rapidfuzz"])

    def test_timer(self):
        with diagnostics.Timer() as t:
            pass
        self.assertGreaterEqual(t.elapsed_ms, 0.0)


class TestFallbackPath(unittest.TestCase):
    def test_fuzzy_match_works_without_rapidfuzz(self):
        with mock.patch.object(diagnostics, "HAVE_RAPIDFUZZ", False):
            self.assertFalse(matching._has_rapidfuzz())
            # difflib + length gate tetap menemukan varian tipis.
            self.assertTrue(
                matching.fuzzy_match_token("hickup", ["hiccup", "hiccups"], 0.78)
            )
            self.assertFalse(
                matching.fuzzy_match_token("banana", ["hiccup", "hiccups"], 0.78)
            )

    def test_scoring_consistent_fallback_vs_current(self):
        spec = load("id")
        segs = [
            {"sec": 0, "text": "segukann"},
            {"sec": 10, "text": "jeguakan"},
            {"sec": 20, "text": "cegukan"},
        ]
        # Jalur apa pun yang aktif sekarang:
        current = score_segments(
            segs, spec, video_id="v", lang="id", cluster_mode="hit_span"
        )
        with mock.patch.object(diagnostics, "HAVE_RAPIDFUZZ", False):
            fallback = score_segments(
                segs, spec, video_id="v", lang="id", cluster_mode="hit_span"
            )
        for f in ("score", "persentase", "core_hits", "kasta", "tier_counts", "hits"):
            self.assertEqual(getattr(current, f), getattr(fallback, f), f)

    def test_fuzzy_still_detects_typo_in_fallback(self):
        spec = load("id")
        with mock.patch.object(diagnostics, "HAVE_RAPIDFUZZ", False):
            res = score_segments(
                [{"sec": 0, "text": "segukann"}], spec,
                video_id="v", lang="id", cluster_mode="hit_span", enable_fuzzy=True,
            )
        self.assertGreater(res.tier_counts.get("CORE", 0) + res.tier_counts.get("TYPO", 0), 0)


if __name__ == "__main__":
    unittest.main()
