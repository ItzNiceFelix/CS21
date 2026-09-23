"""Parity vs fixture Fase 0 (`tests/fixtures/baseline_*.json`) bila ada.

Bila file belum ada -> SKIP (bukan fail), supaya Fase 1 tetap hijau sebelum
skrip baseline dijalankan di Termux.
"""

import glob
import json
import os
import unittest

from cs_core import config
from cs_core.compat import to_legacy
from cs_core.languages import load
from cs_core.scoring import score_segments

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_GLOB = os.path.join(_HERE, "fixtures", "baseline_*.json")


def _fixture_files():
    return sorted(glob.glob(_FIXTURE_GLOB))


@unittest.skipUnless(_fixture_files(), "fixture baseline_*.json belum ada")
class TestParity(unittest.TestCase):
    def test_parity_against_fixtures(self):
        files = _fixture_files()
        for path in files:
            with self.subTest(fixture=os.path.basename(path)):
                self._compare(path)

    def _compare(self, path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        videos = data.get("videos", data if isinstance(data, list) else [])
        for video in videos:
            lang = video.get("lang", "id")
            spec = load(lang)
            segments = video.get("segments") or video.get("raw_segments") or []
            expected = video.get("engine_E") or video.get("analyze_video")
            if not segments or not expected:
                continue
            result = score_segments(
                segments,
                spec,
                video_id=video.get("video_id", ""),
                lang=lang,
                cluster_mode="hit_span",
                dedup_mode="int0",
            )
            actual = to_legacy(result, mode=config.CompatMode.BASELINE, engine="E")
            for key in ("score", "persentase", "cluster_count", "maraton_mins",
                        "is_valid", "kasta", "tier_counts"):
                self.assertEqual(
                    actual.get(key), expected.get(key),
                    f"{path}:{video.get('video_id')}:{key}",
                )


if __name__ == "__main__":
    unittest.main()
