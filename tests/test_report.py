"""Fase 6/T6.4 — report tunggal, highlight span bersih, label IMPROVED, escaping."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from cs_core import report  # noqa: E402
from cs_core import config as _config  # noqa: E402
from cs_core.scoring import score_segments  # noqa: E402


def _spec(lang="id"):
    from cs_core.languages import load
    return load(lang)


def _seg(sec, text, duration=2.0):
    return {"sec": sec, "start": sec, "duration": duration, "text": text}


_SEGMENTS = [
    _seg(0, "halo semua cegukan cegukan"),
    _seg(5, "jegukan lagi cegukan"),
    _seg(2000, "cegukan cegukan cegukan panjang"),
    _seg(2600, "cekukan cegukan"),
    _seg(5000, "cegukan cegukan cegukan"),
    _seg(5600, "cegukan cegukan"),
]


def _result(lang="id"):
    return score_segments(_SEGMENTS, _spec(lang), video_id="vidXYZ", lang=lang,
                          cluster_mode="hit_span", dedup_mode="int0",
                          enable_fuzzy=False)


def _to_legacy(result, mode, engine):
    from cs_core.compat import to_legacy
    return to_legacy(result, mode=mode, engine=engine)


def _no_nested_span(tc, html_out, tag):
    """Assert tidak ada `<span` bersarang di dalam `<span>`."""
    i = 0
    low = html_out.lower()
    while True:
        nxt = low.find("<span", i)
        if nxt == -1:
            break
        end = low.find(">", nxt)
        closer = low.find("</span", end + 1)
        if end == -1 or closer == -1:
            break
        inner = low.find("<span", end + 1)
        tc.assertFalse(
            0 <= inner < closer,
            f"{tag}: nested <span> pada offset {nxt}",
        )
        i = end + 1


class TestBuildHtmlRows(unittest.TestCase):
    def test_highlight_no_nested_span(self):
        out = report.build_html_rows(_result(), mode=_config.CompatMode.IMPROVED,
                                     engine="E")
        self.assertIn("<span class='hl", out)
        _no_nested_span(self, out, "rows")

    def test_no_highlight_baseline_ae(self):
        out = report.build_html_rows(_result(), mode=_config.CompatMode.BASELINE,
                                     engine="AE")
        self.assertNotIn("<span class='hl", out)


class TestBuildHtml(unittest.TestCase):
    def _results(self, mode=None, engine="E"):
        legacy = _to_legacy(_result(), mode or _config.CompatMode.IMPROVED, engine)
        legacy = dict(legacy)
        legacy["video_id"] = "vidXYZ"
        legacy["status"] = "analyzed"
        return [legacy]

    def test_html_has_core_structure(self):
        out = report.build_html("@chan", "tester", self._results(), "id")
        for marker in ("<!DOCTYPE html>", 'class="card', "stats-grid",
                       "tier-strip", "no-trans-grid", 'html lang="id"'):
            self.assertIn(marker, out)
        _no_nested_span(self, out, "html")

    def test_html_no_nested_span(self):
        out = report.build_html("@chan", "tester", self._results(), "id")
        _no_nested_span(self, out, "html")

    def test_html_escapes_query_and_text(self):
        payload = _to_legacy(_result(), mode=_config.CompatMode.IMPROVED, engine="E")
        payload = dict(payload)
        payload["video_id"] = "<script>alert(1)</script>"
        payload["status"] = "analyzed"
        out = report.build_html("<b>evil</b>", "<i>op</i>", [payload], "id")
        self.assertNotIn("<script>", out)
        self.assertNotIn("<b>evil</b>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_html_identical_across_engines_improved(self):
        e = report.build_html("@chan", "op", self._results(engine="E"), "id")
        ie = report.build_html("@chan", "op", self._results(engine="IE"), "id")
        ae = report.build_html("@chan", "op", self._results(engine="AE"), "id")
        self.assertEqual(e, ie)
        self.assertEqual(e, ae)


class TestImprovedLabels(unittest.TestCase):
    def test_improved_full_labels(self):
        result = _result()
        legacy = _to_legacy(result, _config.CompatMode.IMPROVED, "AE")
        label = legacy["kasta_label"]
        self.assertIn("cluster", label)
        # `result.kasta_label` dari `scoring` sudah memuat suffix; IMPROVED
        # memakai label E lengkap apa adanya (bukan varian AE pendek).
        self.assertEqual(label, result.kasta_label)
        # Label E lengkap memuat penanda khas versi E untuk kasta terkait.
        if result.kasta == "AMBIGU":
            self.assertIn("(0 Hit Core)", label)
        if result.kasta == "GOD_MODE":
            self.assertIn("NON-STOP", label)
        if result.kasta == "VALID_HIGH" and result.is_multisesi:
            self.assertIn("SESI KAMBUHAN", label)
        if result.kasta == "SILENT":
            self.assertIn("DETECTED", label)

    def test_baseline_ae_label_shorter(self):
        result = _result()
        base = _to_legacy(result, _config.CompatMode.BASELINE, "AE")
        imp = _to_legacy(result, _config.CompatMode.IMPROVED, "AE")
        # Kasta VALID_HIGH multisisi: AE baseline tanpa "KAMBUHAN"; IMPROVED pakai E.
        self.assertNotIn("KAMBUHAN", base["kasta_label"])
        self.assertIn("KAMBUHAN", imp["kasta_label"])
        self.assertEqual(imp["kasta_label"], result.kasta_label)


class TestCompatModeEnv(unittest.TestCase):
    def test_improved_via_env(self):
        old = os.environ.get("CS_COMPAT")
        try:
            os.environ["CS_COMPAT"] = "IMPROVED"
            self.assertIs(_config.CompatMode.from_env(), _config.CompatMode.IMPROVED)
        finally:
            if old is None:
                os.environ.pop("CS_COMPAT", None)
            else:
                os.environ["CS_COMPAT"] = old

    def test_default_is_baseline(self):
        old = os.environ.pop("CS_COMPAT", None)
        try:
            self.assertIs(_config.CompatMode.from_env(), _config.CompatMode.BASELINE)
        finally:
            if old is not None:
                os.environ["CS_COMPAT"] = old


if __name__ == "__main__":
    unittest.main()
