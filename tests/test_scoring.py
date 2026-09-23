"""Test scoring: kasus sintetis + invariant + determinisme.

Oracle `_baseline_analyze` adalah port bebas dari rumus baseline cs20_engine
(E797-E965) memakai data tier cs_core supaya bisa membandingkan hasil.
"""

import random
import unittest

from cs_core.languages import load
from cs_core.scoring import SCORE_CAP, AnalysisResult, score_segments
from cs_core.compat import to_legacy, _legacy_kasta_label  # noqa: F401


def _oracle_classify(text, spec):
    out = {c.tier: 0 for c in spec.cores}
    for c in spec.cores:
        for pat in c.regexes:
            if pat.search(text):
                out[c.tier] += 1
    return out


def _oracle_analyze(segments, spec, video_id="v", lang="id"):
    """Port verbatim loop baseline (hit_span + int0)."""
    from cs_core.text import normalize

    HIT_LIST = []
    LAST_TEXT = ""
    LAST_SEC = -1
    tier_counts = {c.tier: 0 for c in spec.cores}

    full_text = " ".join(normalize(s) for s in segments)
    if not spec.combined_prefilter.search(full_text):
        return None

    for seg in segments:
        text = normalize(seg)
        start_sec = int(seg.get("sec", seg.get("start", 0)))
        if not text or text == LAST_TEXT:
            continue
        if not spec.combined_prefilter.search(text):
            continue
        if abs(start_sec - LAST_SEC) < 1:
            continue
        hit_tiers = _oracle_classify(text, spec)
        if not any(v > 0 for v in hit_tiers.values()):
            continue
        for tier, count in hit_tiers.items():
            if count > 0:
                tier_counts[tier] += 1
        HIT_LIST.append({"sec": start_sec, "text": text, "tiers": hit_tiers})
        LAST_TEXT = text
        LAST_SEC = start_sec

    if not HIT_LIST:
        return None

    total_duration_min = (HIT_LIST[-1]["sec"] - HIT_LIST[0]["sec"]) // 60
    if total_duration_min > 180:
        GAP = 3600
    elif total_duration_min > 60:
        GAP = 1800
    else:
        GAP = 1200

    clusters = []
    cur = []
    for hit in HIT_LIST:
        if not cur:
            cur = [hit]
        elif hit["sec"] - cur[-1]["sec"] >= GAP:
            clusters.append(cur)
            cur = [hit]
        else:
            cur.append(hit)
    if cur:
        clusters.append(cur)

    CORE_HITS = tier_counts.get("CORE", 0)
    GLOBAL_SCORE = 0
    MARATON_MINS = 0
    VALID_CLUSTERS = 0
    for cl in clusters:
        c_hits = len(cl)
        c_dur_sec = cl[-1]["sec"] - cl[0]["sec"]
        c_dur_min = max(1, c_dur_sec // 60)
        c_core = sum(1 for h in cl if h["tiers"].get("CORE", 0) > 0)
        c_typo = sum(1 for h in cl if h["tiers"].get("TYPO", 0) > 0)
        c_silent = sum(1 for h in cl if h["tiers"].get("SILENT", 0) > 0)
        c_ctx = sum(1 for h in cl if h["tiers"].get("CONTEXT", 0) > 0)
        c_fp = sum(1 for h in cl if h["tiers"].get("FP", 0) > 0)
        c_base = (c_core * 5) + (c_typo * 4) + (c_silent * 4) + (c_ctx * 2) + (c_fp * 1)
        c_density_bonus = min(10, (c_hits // c_dur_min) * 2)
        c_silent_bonus = 15 if c_silent > 0 else 0
        GLOBAL_SCORE += c_base + c_density_bonus + c_silent_bonus
        MARATON_MINS = max(MARATON_MINS, c_dur_min)
        if c_core >= 2:
            VALID_CLUSTERS += 1
    clusters_with_core = sum(1 for cl in clusters if any(h["tiers"].get("CORE", 0) > 0 for h in cl))
    if clusters_with_core > 1:
        GLOBAL_SCORE += 20 * (clusters_with_core - 1)
    PERSENTASE = min(100, (GLOBAL_SCORE * 100) // SCORE_CAP)

    IS_MARATON = (len(clusters) == 1 and MARATON_MINS >= 30 and GLOBAL_SCORE >= 8)
    IS_MULTISESI = (VALID_CLUSTERS >= 2)
    HAS_SILENT = tier_counts.get("SILENT", 0) > 0

    # Efek kasta ke PERSENTASE (E921-965) — termasuk agar parity adil.
    if CORE_HITS == 0:
        PERSENTASE = min(PERSENTASE, 15)
    elif IS_MARATON and PERSENTASE >= 60:
        PERSENTASE = 100
    elif IS_MULTISESI and PERSENTASE >= 60:
        pass
    elif HAS_SILENT and CORE_HITS >= 1:
        PERSENTASE = max(PERSENTASE, 75)

    return {
        "score": GLOBAL_SCORE,
        "persentase": PERSENTASE,
        "cluster_count": len(clusters),
        "maraton_mins": MARATON_MINS,
        "valid_clusters": VALID_CLUSTERS,
        "is_maraton": IS_MARATON,
        "is_multisesi": IS_MULTISESI,
        "has_silent": HAS_SILENT,
        "core_hits": CORE_HITS,
        "tier_counts": tier_counts,
        "_hits": HIT_LIST,
    }


class TestScoringSynthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("id")

    def _run(self, segs, **kw):
        return score_segments(
            segs, self.spec, video_id="vid", lang="id", cluster_mode="hit_span", **kw
        )

    def test_zero_core_is_ambigu(self):
        # "tersedak" -> CONTEXT only, no CORE.
        res = self._run([{"sec": 1, "text": "aku tersedak"}])
        self.assertEqual(res.core_hits, 0)
        self.assertEqual(res.kasta, "AMBIGU")
        self.assertFalse(res.is_valid)
        self.assertLessEqual(res.persentase, 15)

    def test_maraton_god_mode(self):
        # 1 cluster, span >= 30 menit, CORE banyak. Teks WAJIB beda supaya
        # tidak kena dedup `text == LAST_TEXT` baseline.
        segs = [{"sec": i, "text": f"cegukan nomor {i}"} for i in range(0, 1900, 5)]
        res = self._run(segs)
        self.assertTrue(res.is_maraton, (res.maraton_mins, res.score))
        self.assertGreaterEqual(res.persentase, 60)
        self.assertEqual(res.kasta, "GOD_MODE")
        self.assertEqual(res.persentase, 100)
        self.assertTrue(res.is_valid)

    def test_multisesi(self):
        # 2 cluster, masing-masing >=2 CORE, dipisah > gap.
        segs = [
            {"sec": 0, "text": "cegukan satu"},
            {"sec": 30, "text": "cegukan dua"},
            {"sec": 4000, "text": "cegukan tiga"},
            {"sec": 4030, "text": "cegukan empat"},
        ]
        res = self._run(segs)
        self.assertGreaterEqual(res.valid_clusters, 2)
        self.assertTrue(res.is_multisesi)
        self.assertEqual(res.kasta, "VALID_HIGH")
        self.assertTrue(res.is_valid)

    def test_silent(self):
        segs = [{"sec": i * 100, "text": "cegukan terus"} for i in range(20)]
        res = self._run(segs)
        self.assertTrue(res.has_silent)
        self.assertGreaterEqual(res.persentase, 75)
        self.assertEqual(res.kasta, "SILENT")
        self.assertTrue(res.is_valid)

    def test_valid_low(self):
        # core >=1, score rendah, tidak maraton/multisesi/silent.
        segs = [{"sec": 0, "text": "cegukan"}]
        res = self._run(segs)
        self.assertEqual(res.core_hits, 1)
        self.assertEqual(res.kasta, "LOW")
        self.assertFalse(res.is_valid)

    def test_no_match(self):
        res = self._run([{"sec": 0, "text": "halo semua"}])
        self.assertEqual(res.status, "no_match")
        self.assertEqual(res.kasta, "ZONK")
        self.assertEqual(res.hits, ())

    def test_parity_vs_oracle(self):
        cases = [
            [{"sec": 1, "text": "aku tersedak"}],
            [{"sec": i, "text": "cegukan"} for i in range(0, 1900, 5)],
            [
                {"sec": 0, "text": "cegukan"},
                {"sec": 30, "text": "cegukan"},
                {"sec": 4000, "text": "cegukan"},
                {"sec": 4030, "text": "cegukan"},
            ],
            [{"sec": i * 100, "text": "cegukan terus"} for i in range(20)],
            [{"sec": 0, "text": "cegukan"}],
            [{"sec": 10, "text": "nyendawa dan sendawa"}],
        ]
        for segs in cases:
            with self.subTest(segs=segs[:1]):
                res = self._run(segs)
                oracle = _oracle_analyze(segs, self.spec)
                if oracle is None:
                    self.assertEqual(res.status, "no_match")
                    continue
                self.assertEqual(res.score, oracle["score"])
                self.assertEqual(res.persentase, oracle["persentase"])
                self.assertEqual(res.cluster_count, oracle["cluster_count"])
                self.assertEqual(res.maraton_mins, oracle["maraton_mins"])
                self.assertEqual(res.core_hits, oracle["core_hits"])
                self.assertEqual(dict(res.tier_counts), oracle["tier_counts"])
                self.assertEqual(len(res.hits), len(oracle["_hits"]))


class TestInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("en")

    def test_random_invariants(self):
        rng = random.Random(1234)
        words = ["hiccup", "hiccups", "hic", "*hic*", "hickup", "economic hiccup",
                 "still have the hiccups", "hello", "world", "cannot stop the hiccup"]
        for _ in range(1000):
            n = rng.randint(0, 12)
            segs = [
                {"sec": rng.randint(0, 5000), "text": " ".join(rng.choice(words) for _ in range(rng.randint(1, 6)))}
                for _ in range(n)
            ]
            res = score_segments(segs, self.spec, video_id="v", lang="en", cluster_mode="hit_span")
            self.assertLessEqual(res.persentase, 100)
            if res.is_valid:
                self.assertGreater(res.core_hits, 0)

    def test_deterministic(self):
        segs = [
            {"sec": 0, "text": "hiccup"},
            {"sec": 100, "text": "still have the hiccups"},
            {"sec": 4000, "text": "hiccup hiccups"},
        ]
        a = score_segments(segs, self.spec, video_id="v", lang="en", cluster_mode="hit_span")
        b = score_segments(segs, self.spec, video_id="v", lang="en", cluster_mode="hit_span")
        self.assertEqual(a, b)


class TestClusterMode(unittest.TestCase):
    def test_video_duration_vs_hit_span(self):
        spec = load("id")
        # span hit 1400s (23min); video 12000s (200min).
        # hit_span -> gap 1200 -> 2 cluster; video_duration -> gap 3600 -> 1.
        segs = [
            {"sec": 6000, "text": "cegukan a"},
            {"sec": 7400, "text": "cegukan b"},
        ]
        hs = score_segments(segs, spec, video_id="v", lang="id", cluster_mode="hit_span")
        vd = score_segments(
            segs, spec, video_id="v", lang="id",
            cluster_mode="video_duration", video_duration_sec=12000,
        )
        self.assertEqual(hs.cluster_count, 2)
        self.assertEqual(vd.cluster_count, 1)
        self.assertEqual(hs.cluster_mode, "hit_span")
        self.assertEqual(vd.cluster_mode, "video_duration")


class TestCompatLabels(unittest.TestCase):
    def test_legacy_label_ae_variant(self):
        from cs_core import config

        res = score_segments(
            [{"sec": 0, "text": "tersedak"}],
            load("id"),
            video_id="v",
            lang="id",
            cluster_mode="hit_span",
        )
        d = to_legacy(res, mode=config.CompatMode.BASELINE, engine="AE")
        self.assertNotIn("(0 Hit Core)", d["kasta_label"])

    def test_improved_label_full(self):
        from cs_core import config

        res = score_segments(
            [{"sec": 0, "text": "tersedak"}],
            load("id"),
            video_id="v",
            lang="id",
            cluster_mode="hit_span",
        )
        d = to_legacy(res, mode=config.CompatMode.IMPROVED)
        self.assertIn("(0 Hit Core)", d["kasta_label"])

    def test_12_fields(self):
        res = score_segments(
            [{"sec": 0, "text": "cegukan"}], load("id"),
            video_id="v", lang="id", cluster_mode="hit_span",
        )
        d = to_legacy(res)
        required = {
            "status", "status_label", "hits", "tier_counts", "score",
            "persentase", "cluster_count", "maraton_mins", "is_valid",
            "kasta", "kasta_label", "html_rows",
        }
        self.assertTrue(required.issubset(d.keys()))
        self.assertIsInstance(d["hits"], list)


if __name__ == "__main__":
    unittest.main()
