"""Parity engine lama vs fixture Fase 0 (Fase 5/T5.6).

Memanggil langsung:
- `cs20_index_engine._analyze_from_segments` -> field vs `engines.ie`
- `cs20_age_engine._analyze_segments`       -> field vs `engines.ae`

Mode BASELINE (`hit_span` + `int0` + exact) harus byte-for-byte sama.

Engine lama mengimpor `rich` di top-level; bila import gagal modul `sys.exit`
saat import -> ditangkap dan fail dengan pesan jelas (bukan skip senyap).

Bila fixture belum ada -> SKIP.
"""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_FIXTURE = os.path.join(_HERE, "fixtures", "baseline_cegukan_id.json")

# Field skor yang wajib identik dengan fixture.
_PARITY_FIELDS = (
    "score", "persentase", "kasta", "tier_counts",
    "is_valid", "cluster_count", "maraton_mins",
)


def _import_engine(module_name):
    """Import modul engine; bila modul `sys.exit` saat import -> fail jelas."""
    if _REPO not in sys.path:
        sys.path.insert(0, _REPO)
    try:
        return __import__(module_name)
    except SystemExit as exc:
        raise AssertionError(
            f"{module_name} sys.exit({exc.code}) saat import — dependency "
            f"(mis. rich) tak terpasang? Jalankan: pip install rich"
        )


def _assert_hits_parity(tc, act, exp, tag):
    """Cek hits: jumlah, `sec` sebagai int, dan urutannya sama."""
    a_hits = act.get("hits", [])
    e_hits = exp.get("hits", [])
    tc.assertEqual(len(a_hits), len(e_hits), f"{tag}: jumlah hits")
    tc.assertEqual(
        [h.get("sec") for h in a_hits],
        [h.get("sec") for h in e_hits],
        f"{tag}: urutan sec",
    )
    for h in a_hits:
        tc.assertIsInstance(h.get("sec"), int, f"{tag}: sec harus int (skema lama)")


def _to_index_segments(record):
    """Konversi `segments_raw` -> gaya index `{sec:int, text}` (untuk ie/ae)."""
    out = []
    for seg in record.get("segments_raw") or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        if "sec" in seg:
            sec = int(seg["sec"])
        else:
            sec = int(seg.get("start", 0) or 0)
        out.append({"sec": sec, "text": text})
    return out


@unittest.skipUnless(os.path.isfile(_FIXTURE),
                     f"fixture {os.path.basename(_FIXTURE)} belum ada")
class TestEngineParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_FIXTURE, encoding="utf-8") as fh:
            cls.data = json.load(fh)
        cls.lang = (cls.data.get("meta") or {}).get("lang", "id")

        cls.ie = _import_engine("cs20_index_engine")
        cls.ae = _import_engine("cs20_age_engine")
        cls.e = _import_engine("cs20_engine")

        # Set bahasa aktif kedua engine (signature lama tak membawa lang).
        cls.ie._load_lang(cls.lang)
        cls.ae._load_fuzzy_engine(cls.lang)
        cls.e._init_lang(cls.lang)

    def test_parity_ie(self):
        checked = 0
        for video in self.data.get("videos", []):
            exp = (video.get("engines") or {}).get("ie")
            if not isinstance(exp, dict) or "score" not in exp:
                continue
            vid = video.get("video_id", "")
            segments = _to_index_segments(video)
            act = self.ie._analyze_from_segments(vid, "fixtures", segments)
            for key in _PARITY_FIELDS:
                self.assertEqual(
                    act.get(key), exp.get(key),
                    f"ie:{vid}:{key} act={act.get(key)!r} exp={exp.get(key)!r}",
                )
            _assert_hits_parity(self, act, exp, f"ie:{vid}")
            checked += 1
        self.assertGreater(checked, 0, "tak ada video ie dibandingkan")

    def test_parity_ae(self):
        checked = 0
        for video in self.data.get("videos", []):
            exp = (video.get("engines") or {}).get("ae")
            if not isinstance(exp, dict) or "score" not in exp:
                continue
            vid = video.get("video_id", "")
            segments = _to_index_segments(video)
            act = self.ae._analyze_segments(vid, "fixtures", segments)
            for key in _PARITY_FIELDS:
                self.assertEqual(
                    act.get(key), exp.get(key),
                    f"ae:{vid}:{key} act={act.get(key)!r} exp={exp.get(key)!r}",
                )
            _assert_hits_parity(self, act, exp, f"ae:{vid}")
            checked += 1
        self.assertGreater(checked, 0, "tak ada video ae dibandingkan")

    def test_parity_e(self):
        """E: `analyze_video` dgn fetch di-monkeypatch dari `segments_raw`.

        `segments_raw` fixture berbentuk yt-api (`{start, duration}`), dipakai
        apa adanya supaya `_fetch_transcript` tak diubah perilakunya.
        """
        original = self.e._fetch_transcript
        checked = 0
        try:
            for video in self.data.get("videos", []):
                exp = (video.get("engines") or {}).get("e")
                if not isinstance(exp, dict) or "score" not in exp:
                    continue
                vid = video.get("video_id", "")
                raw = video.get("segments_raw") or []
                self.e._fetch_transcript = lambda _vid, _raw=raw: list(_raw)
                act = self.e.analyze_video(vid, "fixtures")
                for key in _PARITY_FIELDS:
                    self.assertEqual(
                        act.get(key), exp.get(key),
                        f"e:{vid}:{key} act={act.get(key)!r} exp={exp.get(key)!r}",
                    )
                self.assertEqual(act.get("status"), exp.get("status"),
                                 f"e:{vid}:status")
                _assert_hits_parity(self, act, exp, f"e:{vid}")
                checked += 1
        finally:
            self.e._fetch_transcript = original
        self.assertGreater(checked, 0, "tak ada video e dibandingkan")


if __name__ == "__main__":
    unittest.main()
