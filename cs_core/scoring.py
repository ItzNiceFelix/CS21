"""Scoring inti — port byte-for-byte rumus baseline (spec §3-§5, arch §7.2).

Satu implementasi menggantikan 3 salinan E/IE/AE. Tidak menyentuh fetch/HTML.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from . import config as _config
from .languages.base import LanguageSpec
from .matching import match_segment as _match_segment
from .text import normalize as _normalize

__all__ = [
    "Hit",
    "AnalysisResult",
    "dedup_key",
    "score_segments",
    "SCORE_CAP",
    "sec_to_hms",
]

SCORE_CAP = 60
_VALID_CLUSTER_GAP_3H = 60 * 60
_VALID_CLUSTER_GAP_1H = 30 * 60
_VALID_CLUSTER_GAP_DEFAULT = 20 * 60


@dataclass(frozen=True)
class Hit:
    sec: float
    time: str
    text: str
    tiers: dict
    url: str


@dataclass(frozen=True)
class AnalysisResult:
    video_id: str
    lang: str
    hits: tuple
    tier_counts: dict
    score: int
    persentase: int
    clusters: tuple
    cluster_count: int
    maraton_mins: int
    valid_clusters: int
    is_maraton: bool
    is_multisesi: bool
    has_silent: bool
    core_hits: int
    kasta: str
    kasta_label: str
    is_valid: bool
    status: str
    status_label: str
    degraded: bool = False
    cluster_mode: str = "video_duration"
    score_cap: int = 60


def sec_to_hms(sec) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ==============================================================================
# DEDUP (P8)
# ==============================================================================
def dedup_key(seg: dict, prev_sec, mode: str) -> bool:
    """True bila segmen harus DIBUANG karena bertabrakan waktu dengan prev.

    Baseline (int): `abs(int(sec) - LAST_SEC) < 1` praktis `== 0`.
    float: bila segmen punya `duration`/`start` non-int, pakai selisih detik
    asli `< 1`.
    """
    if mode == "int0":
        return int(seg.get("sec", seg.get("start", 0))) == int(prev_sec)
    # float: pakai nilai asli (start/ sec bisa float)
    cur = seg.get("sec", seg.get("start", 0))
    return abs(float(cur) - float(prev_sec)) < 1


def _seg_sec(seg: dict) -> float:
    """Ambil waktu segmen; dukung field `sec` (IE/AE) dan `start` (E)."""
    if "sec" in seg:
        return seg.get("sec", 0) or 0
    return seg.get("start", 0) or 0


# ==============================================================================
# CLUSTERING (M9)
# ==============================================================================
def _cluster_gap(total_duration_min: int) -> int:
    if total_duration_min > 180:
        return _VALID_CLUSTER_GAP_3H
    if total_duration_min > 60:
        return _VALID_CLUSTER_GAP_1H
    return _VALID_CLUSTER_GAP_DEFAULT


def _build_clusters(hits: list, span_sec: int, seconds_per_min: int = 60,
                    cluster_mode: str = "hit_span") -> list:
    if not hits:
        return []
    if cluster_mode == "video_duration":
        gap = _cluster_gap(int(span_sec) // int(seconds_per_min))
    else:
        # hit_span: total span dari hit pertama->terakhir (baseline).
        gap = _cluster_gap((hits[-1].sec - hits[0].sec) // 60)
    clusters = []
    current = []
    for hit in hits:
        if not current:
            current = [hit]
        elif hit.sec - current[-1].sec >= gap:
            clusters.append(current)
            current = [hit]
        else:
            current.append(hit)
    if current:
        clusters.append(current)
    return clusters


# ==============================================================================
# SCORE
# ==============================================================================
def score_segments(
    segments,
    spec: LanguageSpec,
    *,
    cluster_mode: str | None = None,
    dedup_mode: str | None = None,
    video_duration_sec=None,
    video_id: str = "",
    lang: str = "",
    enable_fuzzy: bool | None = None,
) -> AnalysisResult:
    """Analisis segmen -> AnalysisResult. Rumus persis baseline spec §3-§5.

    `enable_fuzzy`:
    - `None` (default): baca `config.enable_fuzzy()` (env `CS_ENABLE_FUZZY`).
    - `False`: jalur Fase 1 murni (L1 exact) — hasil byte-for-byte sama.
    - `True`: L1→L2→L3 via `matching.match_segment`, dengan cap fuzzy per
      video (`fuzzy_hits_cap` per tier).
    """
    cluster_mode = cluster_mode or _config.cluster_mode()
    if dedup_mode is None:
        # P8: float bila sumber punya duration, else int0.
        dedup_mode = "float" if _any_duration(segments) else "int0"
    if enable_fuzzy is None:
        enable_fuzzy = _config.enable_fuzzy()

    lang = lang or spec.lang
    base = _no_match(video_id, lang, spec)

    # ── PRE-CHECK CEPAT (E790) ──────────────────────────────────────
    seg_list = list(segments)
    full_text = " ".join(
        _normalize(s) for s in seg_list
    )
    # Prefilter exact hanya bermakna di jalur non-fuzzy; fuzzy butuh kandidat
    # yang justru TIDAK match exact (mis. `jeguakan`), jadi jangan gating.
    if not enable_fuzzy and (
        not spec.combined_prefilter or not spec.combined_prefilter.search(full_text)
    ):
        return base

    # ── ANALISIS PER SEGMEN (E797-838) ──────────────────────────────
    hits: list[Hit] = []
    tier_counts = {t: 0 for t in spec.tier_names()}
    last_text = ""
    last_sec = -1
    # Cap kontribusi fuzzy per tier per VIDEO (lintas segmen, arch §3.3 #6).
    fuzzy_used = {t: 0 for t in spec.tier_names()}

    for seg in seg_list:
        text = _normalize(seg)
        if not text or text == last_text:
            continue
        # Jalur non-fuzzy: prefilter exact per segmen (perilaku Fase 1).
        # Jalur fuzzy: lewati (token kandidat justru bukan match exact).
        if not enable_fuzzy and not spec.combined_prefilter.search(text):
            continue
        if dedup_key(seg, last_sec, dedup_mode):
            continue

        if enable_fuzzy:
            hit_tiers = _match_segment(text, spec, enable_fuzzy=True)
            # exact L1 (1 pattern match) tetap dihitung utk scoring exact;
            # match_segment sudah menandai tier via 0/1.
            exact = _exact_tier_counts(text, spec)
            for tier in hit_tiers:
                if hit_tiers[tier] <= 0:
                    continue
                if exact.get(tier, 0) > 0:
                    hit_tiers[tier] = exact[tier]
                else:
                    # kontribusi fuzzy baru: hormati cap per video.
                    cap = _fuzzy_cap(spec, tier)
                    if fuzzy_used[tier] >= cap:
                        hit_tiers[tier] = 0
                        continue
                    fuzzy_used[tier] += 1
        else:
            hit_tiers = _exact_tier_counts(text, spec)

        if not any(v > 0 for v in hit_tiers.values()):
            continue

        for tier, count in hit_tiers.items():
            if count > 0:
                tier_counts[tier] += 1

        sec_raw = _seg_sec(seg)
        hits.append(
            Hit(
                sec=sec_raw,
                time=sec_to_hms(sec_raw),
                text=text,
                tiers=hit_tiers,
                url=f"https://youtu.be/{video_id}?t={int(sec_raw)}",
            )
        )
        last_text = text
        last_sec = sec_raw

    if not hits:
        return base

    # ── CLUSTER ANALYSIS (E845-867) ─────────────────────────────────
    if video_duration_sec is None:
        span_sec = int(hits[-1].sec - hits[0].sec)
    else:
        span_sec = int(video_duration_sec)
    clusters = _build_clusters(hits, span_sec, 60, cluster_mode)

    # ── SCORING V20 (E869-910) ──────────────────────────────────────
    core_hits = tier_counts.get("CORE", 0)
    global_score = 0
    maraton_mins = 0
    valid_clusters = 0

    for cluster in clusters:
        c_hits = len(cluster)
        c_dur_sec = cluster[-1].sec - cluster[0].sec
        c_dur_min = max(1, int(c_dur_sec) // 60)

        c_core = sum(1 for h in cluster if h.tiers.get("CORE", 0) > 0)
        c_typo = sum(1 for h in cluster if h.tiers.get("TYPO", 0) > 0)
        c_silent = sum(1 for h in cluster if h.tiers.get("SILENT", 0) > 0)
        c_ctx = sum(1 for h in cluster if h.tiers.get("CONTEXT", 0) > 0)
        c_fp = sum(1 for h in cluster if h.tiers.get("FP", 0) > 0)

        c_base = (c_core * 5) + (c_typo * 4) + (c_silent * 4) + (c_ctx * 2) + (c_fp * 1)
        c_density_bonus = min(10, (c_hits // c_dur_min) * 2)  # int div dulu
        c_silent_bonus = 15 if c_silent > 0 else 0

        global_score += c_base + c_density_bonus + c_silent_bonus
        maraton_mins = max(maraton_mins, c_dur_min)
        if c_core >= 2:
            valid_clusters += 1

    clusters_with_core = sum(
        1 for cl in clusters if any(h.tiers.get("CORE", 0) > 0 for h in cl)
    )
    if clusters_with_core > 1:
        global_score += 20 * (clusters_with_core - 1)

    persentase = min(100, (global_score * 100) // SCORE_CAP)

    # ── KASTA V20 (E912-965) ────────────────────────────────────────
    is_maraton = (len(clusters) == 1 and maraton_mins >= 30 and global_score >= 8)
    is_multisesi = (valid_clusters >= 2)
    has_silent = tier_counts.get("SILENT", 0) > 0

    kasta = "ZONK"
    kasta_label = "💀 ZONK"
    is_valid = False

    if core_hits == 0:
        persentase = min(persentase, 15)
        kasta = "AMBIGU"
        kasta_label = "⚠️ AMBIGU — Indikasi Lemah (0 Hit Core)"
    elif is_maraton and persentase >= 60:
        persentase = 100
        kasta = "GOD_MODE"
        kasta_label = f"👑 GOD MODE — MARATON {maraton_mins} MENIT NON-STOP"
        is_valid = True
    elif is_multisesi and persentase >= 60:
        kasta = "VALID_HIGH"
        kasta_label = f"🔥 VALID HIGH — {valid_clusters} SESI KAMBUHAN"
        is_valid = True
    elif has_silent and core_hits >= 1:
        persentase = max(persentase, 75)
        kasta = "SILENT"
        kasta_label = "🤫 VALID — SILENT TREATMENT DETECTED"
        is_valid = True
    elif core_hits >= 3 and persentase >= 60:
        kasta = "VALID_HIGH"
        kasta_label = "✅ VALID HIGH"
        is_valid = True
    elif core_hits >= 1 and persentase >= 40:
        kasta = "VALID"
        kasta_label = "✅ VALID"
        is_valid = True
    elif core_hits >= 1:
        kasta = "LOW"
        kasta_label = "📋 LOW INDICATOR"
    # else: dead branch #8 dihapus (P3) — #1 menangkap core_hits==0,
    # #7 menangkap >=1, jadi tak terjangkau. Perilaku sama.

    kasta_label += f" | {len(clusters)} cluster, {len(hits)} hit"

    return AnalysisResult(
        video_id=video_id,
        lang=lang,
        hits=tuple(hits),
        tier_counts=tier_counts,
        score=global_score,
        persentase=persentase,
        clusters=tuple(tuple(c) for c in clusters),
        cluster_count=len(clusters),
        maraton_mins=maraton_mins,
        valid_clusters=valid_clusters,
        is_maraton=is_maraton,
        is_multisesi=is_multisesi,
        has_silent=has_silent,
        core_hits=core_hits,
        kasta=kasta,
        kasta_label=kasta_label,
        is_valid=is_valid,
        status="analyzed",
        status_label=kasta_label,
        degraded=False,
        cluster_mode=cluster_mode,
        score_cap=SCORE_CAP,
    )


def _exact_tier_counts(text: str, spec: LanguageSpec) -> dict[str, int]:
    """L1 exact: jumlah pattern match per tier (perilaku Fase 1)."""
    out = {t: 0 for t in spec.tier_names()}
    for core in spec.cores:
        for pat in core.regexes or ():
            if pat.search(text):
                out[core.tier] += 1
    return out


def _fuzzy_cap(spec: LanguageSpec, tier: str) -> int:
    """Cap kontribusi fuzzy per tier per video; `FP` tak di-cap (bukan fuzzy).

    `fuzzy_hits_cap <= 0` = tanpa cap. `FP` selalu tanpa cap.
    """
    if tier == "FP":
        return sys.maxsize
    cap = getattr(spec, "fuzzy_hits_cap", 8)
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        return 8
    return cap if cap > 0 else sys.maxsize


def _any_duration(segments) -> bool:
    """P8: sumber punya `duration` (float) -> default dedup float."""
    for seg in segments:
        if isinstance(seg, dict) and "duration" in seg:
            return True
    return False


def _no_match(video_id: str, lang: str, spec: LanguageSpec) -> AnalysisResult:
    return AnalysisResult(
        video_id=video_id,
        lang=lang,
        hits=(),
        tier_counts={t: 0 for t in spec.tier_names()},
        score=0,
        persentase=0,
        clusters=(),
        cluster_count=0,
        maraton_mins=0,
        valid_clusters=0,
        is_maraton=False,
        is_multisesi=False,
        has_silent=False,
        core_hits=0,
        kasta="ZONK",
        kasta_label="💀 ZONK",
        is_valid=False,
        status="no_match",
        status_label="⬜ Tidak Ada Indikasi",
    )
