"""Test normalisasi teks: strip VTT tag, skrip CJK/Devanagari/Telugu utuh."""

import unittest

from cs_core import text
from cs_core.tokens import extract


class TestText(unittest.TestCase):
    def test_strip_vtt_tags(self):
        self.assertEqual(text.strip_vtt_tags("<c>hi</c> there"), "hi there")
        self.assertEqual(text.strip_vtt_tags("<00:01:23.000> hi"), " hi")
        # `[...]` BUKAN tag <...>: baseline hanya buang `<...>`.
        self.assertEqual(
            text.strip_vtt_tags("[00:01:23.000] hello"), "[00:01:23.000] hello"
        )

    def test_normalize_strips_and_keeps_case(self):
        self.assertEqual(text.normalize("  Cegukan  "), "Cegukan")

    def test_normalize_dict_segment(self):
        self.assertEqual(
            text.normalize({"text": "<i>cegukan</i>"}), "cegukan"
        )

    def test_normalize_no_lowercasing(self):
        self.assertEqual(text.normalize("HICCUP"), "HICCUP")

    def test_cjk_kept(self):
        self.assertEqual(text.normalize("しゃっくり"), "しゃっくり")
        self.assertEqual(text.normalize("딸꾹질"), "딸꾹질")

    def test_devanagari_kept(self):
        self.assertEqual(text.normalize("हिचकी"), "हिचकी")

    def test_telugu_kept(self):
        self.assertEqual(text.normalize("ఎక్కిళ్లు"), "ఎక్కిళ్లు")
        # ZWNJ (U+200C) di pattern te tetap utuh lewat NFC.
        self.assertIn("\u200c", text.normalize("హిచ్‌కి"))

    def test_nfc_applied(self):
        decomposed = "e\u0301"
        self.assertEqual(text.normalize(decomposed), "\u00e9")


class TestTokens(unittest.TestCase):
    def test_values(self):
        toks = extract("hi 世界 cegukan")
        self.assertEqual(toks.values, ["hi", "世界", "cegukan"])

    def test_offsets(self):
        toks = extract("a b")
        self.assertEqual([(t.raw, t.start, t.end) for t in toks], [("a", 0, 1), ("b", 2, 3)])


if __name__ == "__main__":
    unittest.main()
