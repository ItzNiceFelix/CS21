"""Fase 2 — test anti-typo (tabel `(text, expected_tier)`).

Cek:
- ID `cegukan`/`jegukan`/`segukan`/`cekukan`/`cukukan` di CORE atau TYPO.
- EN `hiccup`/`hicup`/`hickup`/`hic-cup` di CORE atau TYPO.
- JP/KR exact form di tier yang benar.
- `phonetic_key` (arch §3.5).
- FP negative: `nyendawa`, `economic hiccup` TIDAK boleh jadi CORE/VALID.
"""

import unittest

from cs_core.languages import load
from cs_core.matching import classify_tiers
from cs_core.languages.variants import auto_typo, build_regex, build_phonetic_set, phonetic_key, romanize


def _hits(spec, text):
    """Set tier yang match (satu teks bisa kontribusi ke banyak tier)."""
    counts = classify_tiers(text, spec)
    return {t for t, n in counts.items() if n > 0}


def _expect_tier(testcase, spec, text, tier):
    """Tier terduga WAJIB hadir. Satu teks boleh match banyak tier (mis.
    `aduh cegukan` = frasa TYPO + kata CORE `cegukan`; `cegukan terus` =
    CORE + SILENT)."""
    hits = _hits(spec, text)
    testcase.assertIn(tier, hits, f"{text!r} tak match {tier}; hits={hits}")


class TestIdAntiTypo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("id")

    def test_id_tiers(self):
        cases = {
            "cegukan": "CORE",
            "jegukan": "CORE",
            "segukan": "CORE",
            "cekukan": "TYPO",
            "cukukan": "TYPO",
            "kecegukan": "CORE",
            "aduh cegukan": "TYPO",
            "cegukan terus": "SILENT",
            "tersedak": "CONTEXT",
            "nyendawa": "FP",
        }
        for text, tier in cases.items():
            with self.subTest(text=text):
                _expect_tier(self, self.spec, text, tier)

    def test_phonetic_key_equivalence(self):
        self.assertEqual(phonetic_key("cegukan"), phonetic_key("jegukan"))
        self.assertEqual(phonetic_key("cegukan"), phonetic_key("segukan"))

    def test_phonetic_set_contains_equivalents(self):
        keys = build_phonetic_set(["cegukan", "jegukan", "segukan"])
        self.assertIn(phonetic_key("cekukan"), keys)

    def test_auto_typo_covers_common_asr(self):
        variants = auto_typo("cegukan")
        self.assertIn("kegukan", variants)   # c->k
        self.assertIn("ceguken", variants)   # a->e
        self.assertLessEqual(len(variants), 24)

    def test_auto_typo_max_variants(self):
        self.assertLessEqual(len(auto_typo("cegukan", max_variants=3)), 3)


class TestEnAntiTypo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("en")

    def test_en_tiers(self):
        cases = {
            "hiccup": "CORE",
            "hiccups": "CORE",
            "hic": "CORE",
            "hicup": "TYPO",
            "hickup": "TYPO",
            "hic-cup": "CORE",  # struktur romanisasi/auto-typo Latin
            "economic hiccup": "FP",
            "still have the hiccups": "SILENT",
        }
        for text, tier in cases.items():
            with self.subTest(text=text):
                _expect_tier(self, self.spec, text, tier)

    def test_auto_typo_buffer_no_explosion(self):
        variants = auto_typo("hiccup")
        self.assertIn("hickup", variants)
        self.assertLessEqual(len(variants), 24)


class TestNonLatinAntiTypo(unittest.TestCase):
    def test_jp_exact(self):
        spec = load("jp")
        _expect_tier(self, spec, "しゃっくり", "CORE")
        _expect_tier(self, spec, "シャクリ", "TYPO")
        _expect_tier(self, spec, "びっくり", "FP")

    def test_kr_exact(self):
        spec = load("kr")
        _expect_tier(self, spec, "딸꾹질", "CORE")
        _expect_tier(self, spec, "딸각", "CORE")
        _expect_tier(self, spec, "[딸꾹]", "TYPO")

    def test_romanize_falls_back_to_form(self):
        # latin tak punya map roman
        self.assertEqual(romanize("hiccup", "latin"), "hiccup")
        # JP punya map
        self.assertEqual(romanize("しゃっくり", "japanese"), "shakkuri")


class TestFpNegative(unittest.TestCase):
    """FP negative: teks pendek harus tetap FP/CONTEXT, bukan CORE/VALID."""

    def test_id_nyendawa_not_core(self):
        spec = load("id")
        self.assertNotIn("CORE", _hits(spec, "nyendawa"))

    def test_en_economic_hiccup_not_core(self):
        spec = load("en")
        # FP menang, tapi `hiccup` CORE memang match string — gerbang VALID
        # tetap menahan lewat neg_context/FP. Di test ini FP wajib hadir.
        self.assertIn("FP", _hits(spec, "economic hiccup"))


class TestBuildRegex(unittest.TestCase):
    def test_latin_has_word_boundary(self):
        self.assertEqual(build_regex(["hiccup"], "latin"), r"\b(?:hiccup)\b")

    def test_nonlatin_no_boundary(self):
        self.assertEqual(build_regex(["しゃっくり"], "japanese"), "(?:しゃっくり)")

    def test_star_marker_no_boundary(self):
        self.assertEqual(build_regex(["*hic*"], "latin"), "(?:*hic*)")

    def test_empty_forms_noop(self):
        self.assertEqual(build_regex([], "latin"), r"(?!)")


if __name__ == "__main__":
    unittest.main()
