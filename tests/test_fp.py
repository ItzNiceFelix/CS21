"""Fase 3 — anti-false-positive: FP wajib tetap non-VALID.

Kasus yang tidak boleh menjadi VALID (arch §3.3, spec §2):
- id: `nyendawa`, `sendawa`
- en: `economic hiccup`, `minor hiccup`
- kalimat panjang tanpa cegukan -> ZONK / no_match.
"""

import unittest

from cs_core.languages import load
from cs_core.scoring import score_segments


def _score(segs, lang, *, enable_fuzzy=True):
    spec = load(lang)
    return score_segments(
        segs, spec, video_id="v", lang=lang,
        cluster_mode="hit_span", enable_fuzzy=enable_fuzzy,
    )


class TestFpNonValid(unittest.TestCase):
    def test_id_sendawa_family(self):
        for text in ("nyendawa", "sendawa"):
            with self.subTest(text=text):
                res = _score([{"sec": 0, "text": text}], "id")
                self.assertFalse(res.is_valid, res.kasta)
                self.assertEqual(res.core_hits, 0, res.tier_counts)

    def test_en_economic_minor_hiccup(self):
        for text in ("economic hiccup", "minor hiccup"):
            with self.subTest(text=text):
                res = _score([{"sec": 0, "text": text}], "en")
                self.assertFalse(res.is_valid, res.kasta)
                # FP wajib hadir (penanda konteks negatif).
                self.assertGreater(res.tier_counts.get("FP", 0), 0)

    def test_fp_repeated_never_valid(self):
        # Banyak segmen FP: `economic hiccup` literal memuat kata `hiccup`, jadi
        # CORE exact boleh tetap terhitung (perilaku baseline); yang WAJIB:
        # kasta tetap non-VALID (LOW/AMBIGU) walau FP berulang.
        segs = [{"sec": i * 60, "text": "economic hiccup"} for i in range(10)]
        res = _score(segs, "en")
        self.assertFalse(res.is_valid, (res.kasta, res.core_hits))
        self.assertGreater(res.tier_counts.get("FP", 0), 0)


class TestLongTextNoHiccup(unittest.TestCase):
    def test_long_id_sentence_not_core(self):
        sentence = (
            "hari ini saya pergi ke pasar membeli sayur dan buah segar "
            "lalu pulang ke rumah dan beristirahat dengan tenang"
        )
        segs = [{"sec": i * 30, "text": sentence} for i in range(10)]
        res = _score(segs, "id")
        self.assertFalse(res.is_valid)
        self.assertEqual(res.core_hits, 0)
        self.assertEqual(res.status, "no_match")

    def test_long_en_sentence_not_core(self):
        sentence = (
            "the quick brown fox jumps over the lazy dog while the "
            "weather remains calm and the market stays stable"
        )
        segs = [{"sec": i * 30, "text": sentence} for i in range(10)]
        res = _score(segs, "en")
        self.assertFalse(res.is_valid)
        self.assertEqual(res.core_hits, 0)


if __name__ == "__main__":
    unittest.main()
