"""Fase 3 — typo ASR yang Fase 1 exact TIDAK tangkap, kini tertangkap fuzzy/L3.

Aturan (arch §3.3): varian boleh masuk TYPO/varian, tapi TIDAK boleh naik jadi
kasta VALID tanpa CORE.
"""

import unittest

from cs_core.languages import load
from cs_core.matching import match_segment
from cs_core.scoring import score_segments


class TestIdFuzzy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("id")

    def test_fuzzy_detects_asr_typos(self):
        # Fase 1 exact tak menangkap ini; fuzzy/L3 harus menandai CORE/TYPO.
        for text in ("segukann", "cegukann", "jeguakan"):
            with self.subTest(text=text):
                hits = match_segment(text, self.spec, enable_fuzzy=True)
                self.assertGreater(hits.get("CORE", 0) + hits.get("TYPO", 0), 0, hits)

    def test_typo_transpose_typo_only_not_valid(self):
        # `jeguakan` = transpose → TYPO, tanpa CORE → kasta non-VALID.
        res = score_segments(
            [{"sec": 0, "text": "jeguakan"}], self.spec,
            video_id="v", lang="id", cluster_mode="hit_span", enable_fuzzy=True,
        )
        self.assertFalse(res.is_valid, res.kasta)
        self.assertEqual(res.core_hits, 0)

    def test_noise_token_not_matched(self):
        hits = match_segment("makanan enak sekali", self.spec, enable_fuzzy=True)
        self.assertEqual(sum(hits.values()), 0, hits)


class TestEnFuzzy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("en")

    def test_hickkup_detected_as_typo(self):
        hits = match_segment("hickkup", self.spec, enable_fuzzy=True)
        self.assertGreater(hits.get("CORE", 0) + hits.get("TYPO", 0), 0, hits)

    def test_hickkup_not_valid_without_core(self):
        res = score_segments(
            [{"sec": 0, "text": "hickkupp"}], self.spec,
            video_id="v", lang="en", cluster_mode="hit_span", enable_fuzzy=True,
        )
        self.assertFalse(res.is_valid, (res.kasta, res.core_hits))


class TestDisabledFuzzyRegression(unittest.TestCase):
    def test_disable_fuzzy_no_new_detection(self):
        # Fase 1 exact: `jeguakan` tidak match. enable_fuzzy=False harus sama.
        spec = load("id")
        off = score_segments(
            [{"sec": 0, "text": "jeguakan"}], spec,
            video_id="v", lang="id", cluster_mode="hit_span", enable_fuzzy=False,
        )
        self.assertEqual(off.tier_counts.get("CORE", 0) + off.tier_counts.get("TYPO", 0), 0)

    def test_enable_fuzzy_never_changes_exact_hits(self):
        spec = load("id")
        segs = [{"sec": i, "text": "cegukan"} for i in range(0, 600, 5)]
        on = score_segments(segs, spec, video_id="v", lang="id",
                            cluster_mode="hit_span", enable_fuzzy=True)
        off = score_segments(segs, spec, video_id="v", lang="id",
                             cluster_mode="hit_span", enable_fuzzy=False)
        for f in ("score", "core_hits", "kasta", "tier_counts", "hits"):
            self.assertEqual(getattr(on, f), getattr(off, f), f)


if __name__ == "__main__":
    unittest.main()
