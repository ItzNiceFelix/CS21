"""Test dedup P8: float vs int0 beda perilaku pada dua segmen beda durasi
di detik yang sama.
"""

import unittest

from cs_core.scoring import dedup_key


class TestDedup(unittest.TestCase):
    def test_int0_flags_same_second(self):
        prev = 10
        seg = {"sec": 10, "text": "x"}
        self.assertTrue(dedup_key(seg, prev, "int0"))

    def test_int0_ignores_different_second(self):
        seg = {"sec": 11, "text": "x"}
        self.assertFalse(dedup_key(seg, 10, "int0"))

    def test_float_flags_same_second_as_int(self):
        # int(10.9) == int(10) -> int0 buang, float juga buang (<1).
        self.assertTrue(dedup_key({"sec": 10.9}, 10, "float"))
        self.assertTrue(dedup_key({"sec": 10.9}, 10, "int0"))

    def test_float_keeps_sub_second_distinct(self):
        # start 0.2 vs prev 0.9 -> abs=0.7 < 1 -> float buang
        self.assertTrue(dedup_key({"sec": 0.2, "duration": 1.0}, 0.9, "float"))

    def test_float_keeps_1_sec_apart(self):
        self.assertFalse(dedup_key({"sec": 1.2, "duration": 1.0}, 0.2, "float"))

    def test_divergent_behavior(self):
        """Dua segmen beda durasi di detik int yang sama.

        sec 10.4 & sec 10.9 -> int() keduanya 10 => int0 membuang (==).
        float: abs(10.9 - 10.4) = 0.5 < 1 -> juga membuang.
        Tapi sec 10.4 vs prev 11.6 (int 10 via int(10.4)? no: prev int 11).
        Pakai pasangan yang jelas: sec 5.9 vs prev 6.1 -> int0: 6 vs 5 -> simpan;
        float: abs 0.2 < 1 -> buang.
        """
        seg = {"sec": 6.1, "duration": 0.9}
        prev = 5.9
        # int0: int(6.1)=6 != int(5.9)=5 -> tidak dedup
        self.assertFalse(dedup_key(seg, prev, "int0"))
        # float: 0.2 < 1 -> dedup
        self.assertTrue(dedup_key(seg, prev, "float"))

    def test_default_float_when_duration_present(self):
        from cs_core.languages import load
        from cs_core.scoring import score_segments

        spec = load("id")
        segs = [
            {"start": 5.9, "duration": 1.0, "text": "cegukan pertama"},
            {"start": 6.1, "duration": 1.0, "text": "cegukan kedua"},
        ]
        res = score_segments(segs, spec, video_id="x", lang="id", cluster_mode="hit_span")
        # float default: dua segmen 0.2 detik terpisah -> 1 hit.
        self.assertEqual(len(res.hits), 1)

    def test_default_int0_without_duration(self):
        from cs_core.languages import load
        from cs_core.scoring import score_segments

        spec = load("id")
        segs = [
            {"sec": 5, "text": "cegukan pertama"},
            {"sec": 6, "text": "cegukan kedua"},
        ]
        res = score_segments(segs, spec, video_id="x", lang="id", cluster_mode="hit_span")
        self.assertEqual(len(res.hits), 2)


if __name__ == "__main__":
    unittest.main()
