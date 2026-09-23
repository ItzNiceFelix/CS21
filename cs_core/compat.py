"""Shim hasil baru -> skema dict lama.

Konsumen hilir (HTML/Discord/status.json) membaca 12 field tetap. `to_legacy`
mengembalikan `hits` sebagai `list[dict]` supaya `json.dump` sama baseline.
"""

from __future__ import annotations

from . import config as _config
from .report import build_html_rows  # noqa: F401 (re-export)


def _legacy_label(kasta: str, engine: str = "E") -> str:
    """Label kasta varian engine asal (BASELINE).

    engine "E": label lengkap (sama dengan default baru).
    engine "AE"/"IE": varian lama tanpa `(0 Hit Core)` / `NON-STOP` /
      `SESI KAMBUHAN` / `DETECTED`.
    """
    labels = {
        "AMBIGU": "⚠️ AMBIGU — Indikasi Lemah (0 Hit Core)",
        "GOD_MODE": None,  # butuh maraton_mins
        "VALID_HIGH_SESI": None,  # butuh valid_clusters
        "SILENT": "🤫 VALID — SILENT TREATMENT DETECTED",
        "VALID_HIGH": "✅ VALID HIGH",
        "VALID": "✅ VALID",
        "LOW": "📋 LOW INDICATOR",
        "ZONK": "💀 ZONK",
    }
    if engine in ("AE", "IE"):
        labels = {
            "AMBIGU": "⚠️ AMBIGU — Indikasi Lemah",
            "SILENT": "VALID — SILENT TREATMENT",
            **labels,
        }
    return labels.get(kasta, "💀 ZONK")


def _legacy_kasta_label(result, engine: str = "E") -> str:
    """Bangun label kasta panjang sesuai engine, lalu tambah suffix cluster/hit."""
    kasta = result.kasta
    if engine in ("AE", "IE"):
        if kasta == "AMBIGU":
            label = "⚠️ AMBIGU — Indikasi Lemah"
        elif kasta == "GOD_MODE":
            label = f"👑 GOD MODE — MARATON {result.maraton_mins} MENIT"
        elif kasta == "VALID_HIGH" and result.is_multisesi:
            label = f"🔥 VALID HIGH — {result.valid_clusters} SESI"
        elif kasta == "SILENT":
            label = "VALID — SILENT TREATMENT"
        else:
            label = _BASE.get(kasta, "💀 ZONK")
    else:
        if kasta == "GOD_MODE":
            label = f"👑 GOD MODE — MARATON {result.maraton_mins} MENIT NON-STOP"
        elif kasta == "VALID_HIGH" and result.is_multisesi:
            label = f"🔥 VALID HIGH — {result.valid_clusters} SESI KAMBUHAN"
        else:
            label = _BASE.get(kasta, "💀 ZONK")
    return label + f" | {result.cluster_count} cluster, {len(result.hits)} hit"


_BASE = {
    "AMBIGU": "⚠️ AMBIGU — Indikasi Lemah (0 Hit Core)",
    "SILENT": "🤫 VALID — SILENT TREATMENT DETECTED",
    "VALID_HIGH": "✅ VALID HIGH",
    "VALID": "✅ VALID",
    "LOW": "📋 LOW INDICATOR",
    "ZONK": "💀 ZONK",
}


def _hit_to_dict(hit) -> dict:
    return {
        "sec": hit.sec,
        "time": hit.time,
        "text": hit.text,
        "tiers": dict(hit.tiers),
        "url": hit.url,
    }


def to_legacy(result, *, mode=None, engine: str = "E") -> dict:
    """Konversi `AnalysisResult` -> dict 12-field skema lama."""
    if mode is None:
        mode = _config.CompatMode.from_env()
    elif isinstance(mode, str):
        mode = _config.CompatMode(mode)

    hits = [_hit_to_dict(h) for h in result.hits]

    if mode is _config.CompatMode.BASELINE:
        kasta_label = _legacy_kasta_label(result, engine=engine)
    else:
        kasta_label = result.kasta_label

    return {
        "status": result.status,
        "status_label": result.status_label,
        "hits": hits,
        "tier_counts": dict(result.tier_counts),
        "score": result.score,
        "persentase": result.persentase,
        "cluster_count": result.cluster_count,
        "maraton_mins": result.maraton_mins,
        "is_valid": result.is_valid,
        "kasta": result.kasta,
        "kasta_label": kasta_label,
        "html_rows": build_html_rows(result, mode, engine=engine),
    }
