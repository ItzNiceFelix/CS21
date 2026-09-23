"""Parity vs fixture Fase 0 (`tests/fixtures/baseline_*.json`).

Fixture format (lihat tools/baseline_capture.py):
  { "meta": {...}, "videos": [ {"video_id","source","segments_raw","engines":{"e","ie","ae"}} ] }

Kontrak: `cs_core.scoring.score_segments` dalam mode BASELINE
(cluster_mode="hit_span", dedup_mode="int0") harus mereproduksi field skor
engine lama (e/ie/ae) untuk input segmen yang sama.

Mengapa int0+hit_span: engine lama memakai dedup int (`abs(sec-last)<1` pada
int = buang detik sama) dan cluster gap dari span hit. P8/M9 (float/video_
duration) diuji terpisah dan TIDAK berlaku di sini.

Bila file fixture belum ada -> SKIP (bukan fail).
"""

import glob
import json
import os
import sys
import unittest

from cs_core import config
from cs_core.compat import to_legacy
from cs_core.languages import load
from cs_core.scoring import score_segments

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_GLOB = os.path.join(_HERE, "fixtures", "baseline_*.json")

# Field yang harus identik dengan engine lama (mode BASELINE).
_PARITY_FIELDS = ("score", "persentase", "cluster_count", "maraton_mins",
                  "is_valid", "kasta")


def _fixture_files():
    return sorted(glob.glob(_FIXTURE_GLOB))


def _engine_segments(record):
    """Konversi `segments_raw` apa pun -> gaya index `{sec,text}` (untuk ie/ae).

    Engine e memakai segmen mentah (start/duration); ie/ae memakai sec/text.
    """
    raw = record.get("segments_raw") or []
    idx = []
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        if "sec" in seg:
            sec = int(seg["sec"])
        else:
            sec = int(seg.get("start", 0) or 0)
        idx.append({"sec": sec, "text": text})
    return raw, idx


@unittest.skipUnless(_fixture_files(), "fixture baseline_*.json belum ada")
class TestParity(unittest.TestCase):
    def test_parity_against_fixtures(self):
        checked = 0
        for path in _fixture_files():
            with self.subTest(fixture=os.path.basename(path)):
                checked += self._compare(path)
        # Pastikan test tidak "lulus palsu" karena semua video di-skip.
        self.assertGreater(checked, 0, "tidak ada video yang benar-benar dibandingkan")

    def _compare(self, path) -> int:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return 0
        videos = data.get("videos", [])
        lang = (data.get("meta") or {}).get("lang", "id")
        spec = load(lang)
        checked = 0

        for video in videos:
            engines = video.get("engines") or {}
            exp_e = engines.get("e")
            exp_ie = engines.get("ie")
            exp_ae = engines.get("ae")
            if not isinstance(exp_e, dict) or "score" not in exp_e:
                continue

            raw_segments, idx_segments = _engine_segments(video)
            vid = video.get("video_id", "")

            # ── Engine E: segmen mentah (start/duration), baseline e ──
            res_e = score_segments(
                raw_segments, spec, video_id=vid, lang=lang,
                cluster_mode="hit_span", dedup_mode="int0",
                enable_fuzzy=False,
            )
            act_e = to_legacy(res_e, mode=config.CompatMode.BASELINE, engine="E")
            for key in _PARITY_FIELDS:
                self.assertEqual(
                    act_e.get(key), exp_e.get(key),
                    f"{os.path.basename(path)}:{vid}:E:{key} "
                    f"(actual={act_e.get(key)} expected={exp_e.get(key)})",
                )

            # ── Engine IE/AE: segmen {sec,text}, baseline ie/ae ──
            for tag, exp in (("ie", exp_ie), ("ae", exp_ae)):
                if not isinstance(exp, dict) or "score" not in exp:
                    continue
                res = score_segments(
                    idx_segments, spec, video_id=vid, lang=lang,
                    cluster_mode="hit_span", dedup_mode="int0",
                    enable_fuzzy=False,
                )
                act = to_legacy(res, mode=config.CompatMode.BASELINE, engine=tag.upper())
                for key in _PARITY_FIELDS:
                    self.assertEqual(
                        act.get(key), exp.get(key),
                        f"{os.path.basename(path)}:{vid}:{tag}:{key} "
                        f"(actual={act.get(key)} expected={exp.get(key)})",
                    )
            checked += 1
        return checked


if __name__ == "__main__":
    unittest.main()
