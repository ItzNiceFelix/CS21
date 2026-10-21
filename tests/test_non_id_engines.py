"""Perilaku engine non-Indonesia: boundary per aksara, tier tunggal, similarity.

Bahasa Indonesia sengaja TIDAK diuji di sini — perilakunya dikunci oleh
`tests/test_anti_typo.py` + fixture dan tidak boleh berubah.
"""

import unittest

from cs_core.languages import load
from cs_core.languages.variants import MIN_AUTO_TYPO_LEN, auto_typo, build_regex
from cs_core.matching import match_segment
from cs_core.scoring import score_segments

def _hits(text, lang, *, fuzzy=True):
    return {k: v for k, v in match_segment(text, load(lang), enable_fuzzy=fuzzy).items() if v}

class TestDevanagariBoundary(unittest.TestCase):
    """`\\b` Python tak pernah cocok pada form berakhiran matra (`ी`, `ు`).

    Tanpa boundary eksplisit, pattern jatuh ke substring polos dan menangkap
    form di tengah kata lain.
    """

    def test_hindi_form_found_in_sentence(self):
        # Kalimat dengan spasi: harus match (dulu gagal karena `\b`).
        self.assertIn("CORE", _hits("मुझे हिचकी आई", "in", fuzzy=False))

    def test_hindi_form_not_matched_inside_word(self):
        # Menempel pada kata lain: tidak boleh match.
        self.assertEqual(_hits("हिचकीआई", "in", fuzzy=False), {})

    def test_telugu_form_found_in_sentence(self):
        self.assertIn("CORE", _hits("నాకు ఎక్కిళ్లు వస్తున్నాయి", "te", fuzzy=False))

    def test_telugu_form_not_matched_inside_word(self):
        self.assertEqual(_hits("ఎక్కిళ్లువస్తున్నాయి", "te", fuzzy=False), {})

    def test_merged_language_covers_both_scripts(self):
        # `in` menggabungkan Hindi + Telugu; boundary harus menutup keduanya.
        self.assertIn("CORE", _hits("मुझे हिचकी आई", "in", fuzzy=False))
        self.assertIn("CORE", _hits("నాకు ఎక్కిళ్లు వస్తున్నాయి", "in", fuzzy=False))
        self.assertEqual(_hits("हिचकीआई", "in", fuzzy=False), {})

class TestSpacelessScriptsKeepSubstring(unittest.TestCase):
    """Thai/JP/KR menempelkan partikel pada kata — substring memang benar."""

    def test_japanese_particle_attached(self):
        self.assertIn("CORE", _hits("しゃっくりが止まらない", "jp", fuzzy=False))

    def test_korean_particle_attached(self):
        self.assertIn("CORE", _hits("딸꾹질이 안 멈춰", "kr", fuzzy=False))

    def test_thai_in_sentence(self):
        self.assertIn("CORE", _hits("ฉันมีอาการสะอึก", "th", fuzzy=False))

class TestSingleTierPerWord(unittest.TestCase):
    """Satu kata = satu tier. Dulu `hiccup` dihitung CORE + TYPO sekaligus."""

    def test_en_forms_hit_one_tier_only(self):
        spec = load("en")
        for word in ("hiccup", "hiccups", "hic", "hiccough",
                     "hicup", "hicups", "hickup", "hickups", "hiccoughs"):
            with self.subTest(word=word):
                tiers = {k: v for k, v in match_segment(word, spec, enable_fuzzy=False).items() if v}
                self.assertEqual(len(tiers), 1, f"{word}: {tiers}")

    def test_jp_chinese_form_hits_one_tier(self):
        tiers = _hits("吃逆", "jp", fuzzy=False)
        self.assertEqual(len(tiers), 1, tiers)

    def test_score_parity_with_indonesian(self):
        """1/3/6/8 hit harus menghasilkan persentase sama di semua bahasa."""
        cases = {
            "id": "cegukan", "en": "hiccup", "jp": "しゃっくり", "kr": "딸꾹질",
            "in": "हिचकी", "th": "สะอึก", "te": "ఎక్కిళ్లు",
        }
        baseline = None
        for lang, word in cases.items():
            spec = load(lang)
            row = []
            for n in (1, 3, 6, 8):
                segs = [{"sec": i * 300, "text": f"segmen {i} ada {word} di sini"} for i in range(n)]
                res = score_segments(segs, spec, video_id="v", lang=lang,
                                     cluster_mode="hit_span", dedup_mode="int0",
                                     enable_fuzzy=False)
                row.append((res.persentase, res.kasta))
            if baseline is None:
                baseline = row
            self.assertEqual(row, baseline, f"{lang}: {row} != {baseline}")

class TestAutoTypoShortForms(unittest.TestCase):
    """Form 3 huruf tidak boleh di-generate variannya (1 edit = 33% kata)."""

    def test_short_form_generates_nothing(self):
        self.assertEqual(auto_typo("hic"), set())
        self.assertEqual(auto_typo("abc"), set())

    def test_min_length_form_still_generates(self):
        self.assertGreaterEqual(len(auto_typo("h" * MIN_AUTO_TYPO_LEN)), 0)
        self.assertIn("hickup", auto_typo("hiccup"))

    def test_no_real_word_leaks_into_core(self):
        spec = load("en")
        for word in ("his", "hiss", "hec", "hik", "heck", "sic", "sick"):
            with self.subTest(word=word):
                self.assertEqual(_hits(word, "en"), {}, word)

class TestPhoneticLayerScope(unittest.TestCase):
    """Aturan fonetik Indonesia (`c→s`, `k→g`) tidak berlaku untuk bahasa lain."""

    def test_english_phonetic_collision_is_gone(self):
        # `phonetic_key("hic") == "his"` dulu membuat `hiss` jadi CORE lewat L3.
        # Sekarang L3 mati untuk en: `hiss` tidak match sama sekali.
        self.assertEqual(_hits("hiss", "en"), {})

    def test_hics_never_reaches_core(self):
        # `hics` masih boleh TYPO lewat fuzzy L2 (0.80 vs `hicups`) — itu typo
        # ASR yang sah — tapi tidak boleh jadi CORE lewat jalur fonetik.
        hits = _hits("hics", "en")
        self.assertEqual(hits.get("CORE", 0), 0, hits)
        self.assertLessEqual(set(hits), {"TYPO"}, hits)

    def test_indonesian_phonetic_still_works(self):
        # id tetap memakai L3 seperti sebelumnya.
        from cs_core.matching import PHONETIC_LANGS
        self.assertIn("id", PHONETIC_LANGS)
        self.assertNotIn("en", PHONETIC_LANGS)

class TestSimilarityReported(unittest.TestCase):
    """Ambang similarity kini dilaporkan, bukan cuma gerbang biner."""

    def test_exact_hit_similarity_is_one(self):
        spec = load("id")
        res = score_segments([{"sec": 0, "text": "cegukan"}], spec, video_id="v",
                             lang="id", cluster_mode="hit_span", dedup_mode="int0",
                             enable_fuzzy=True)
        self.assertEqual(res.hits[0].similarity.get("CORE"), 1.0)
        self.assertEqual(res.mean_similarity, 1.0)

    def test_fuzzy_hit_reports_real_ratio(self):
        spec = load("id")
        res = score_segments([{"sec": 0, "text": "cegkuanku"}], spec, video_id="v",
                             lang="id", cluster_mode="hit_span", dedup_mode="int0",
                             enable_fuzzy=True)
        sim = res.hits[0].similarity.get("CORE")
        self.assertIsNotNone(sim)
        self.assertGreater(sim, 0.8)
        self.assertLess(sim, 1.0)
        self.assertAlmostEqual(res.mean_similarity, sim)

    def test_no_core_means_no_similarity(self):
        spec = load("id")
        res = score_segments([{"sec": 0, "text": "segukan"}], spec, video_id="v",
                             lang="id", cluster_mode="hit_span", dedup_mode="int0",
                             enable_fuzzy=True)
        self.assertIsNone(res.mean_similarity)

    def test_legacy_payload_carries_similarity(self):
        from cs_core.compat import to_legacy
        spec = load("id")
        res = score_segments([{"sec": 0, "text": "cegukan"}], spec, video_id="v",
                             lang="id", cluster_mode="hit_span", dedup_mode="int0",
                             enable_fuzzy=True)
        legacy = to_legacy(res, mode="BASELINE", engine="E")
        self.assertEqual(legacy["mean_similarity"], 1.0)
        self.assertEqual(legacy["hits"][0]["similarity"]["CORE"], 1.0)

class TestBuildRegexBoundaries(unittest.TestCase):
    def test_latin_uses_word_boundary(self):
        self.assertEqual(build_regex(["hiccup"], "latin"), r"\b(?:hiccup)\b")

    def test_devanagari_uses_range_lookaround(self):
        pat = build_regex(["हिचकी"], "devanagari")
        self.assertIn("(?<!", pat)
        self.assertIn("(?!", pat)

    def test_spaceless_script_has_no_boundary(self):
        self.assertEqual(build_regex(["しゃっくり"], "japanese"), "(?:しゃっくり)")

    def test_merged_covers_hindi_and_telugu(self):
        pat = build_regex(["हिचकी"], "devanagari", merged=True)
        self.assertIn(r"\u0C00", pat)


if __name__ == "__main__":
    unittest.main()
