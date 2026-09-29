"""Config runtime cs_core. Semua dari env, default aman untuk BASELINE.

- `CompatMode`: env `CS_COMPAT` (default `BASELINE`).
- `CLUSTER_MODE`: `video_duration` (default) | `hit_span`.
- `DEDUP_MODE`: `float` | `int0`.
- `CACHE_TTL_DAYS`: default 30.
- `CS_FUZZY_MODE`: `auto` (default) | `on` | `off` — `auto` menyalakan fuzzy
  hanya bila rapidfuzz punya ekstensi native (di Termux biasanya tidak).
- `CS_ENABLE_FUZZY`: `1` | `0` — override mentah; ditulis otomatis oleh
  `apply_fuzzy_mode()` supaya setelan ikut ke engine anak.
- `CS_FUZZY_THRESHOLD`: ambang default bila tier tak mendeklarasikan.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

__all__ = [
    "CompatMode",
    "CLUSTER_MODE_ENV",
    "DEDUP_MODE_ENV",
    "CACHE_TTL_DAYS_ENV",
    "ENABLE_FUZZY_ENV",
    "FUZZY_MODE_ENV",
    "FUZZY_THRESHOLD_ENV",
    "DEFAULT_FUZZY_THRESHOLD",
    "DEFAULT_FUZZY_MODE",
    "DEFAULT_FUZZY_HITS_CAP",
    "cluster_mode",
    "dedup_mode",
    "cache_ttl_days",
    "enable_fuzzy",
    "fuzzy_threshold",
    "fuzzy_mode",
    "apply_fuzzy_mode",
    "have_native_rapidfuzz",
]

CLUSTER_MODE_ENV = "CLUSTER_MODE"
DEDUP_MODE_ENV = "DEDUP_MODE"
CACHE_TTL_DAYS_ENV = "CACHE_TTL_DAYS"
ENABLE_FUZZY_ENV = "CS_ENABLE_FUZZY"
FUZZY_MODE_ENV = "CS_FUZZY_MODE"
FUZZY_THRESHOLD_ENV = "CS_FUZZY_THRESHOLD"

VALID_CLUSTER_MODES = ("video_duration", "hit_span")
VALID_DEDUP_MODES = ("float", "int0")
DEFAULT_CLUSTER_MODE = "video_duration"
DEFAULT_DEDUP_MODE = "float"
DEFAULT_CACHE_TTL_DAYS = 30
DEFAULT_ENABLE_FUZZY = True
# Mode fuzzy: `auto` menyalakan L2/L3 hanya bila akselerasi native tersedia.
DEFAULT_FUZZY_MODE = "auto"
# Ambang tingkat bahasa (tier boleh override di forms.py).
DEFAULT_FUZZY_THRESHOLD = 0.85

def have_native_rapidfuzz() -> bool:
    """True hanya bila rapidfuzz punya ekstensi native (`.so`/`.pyd`).

    Di Termux/Android, pip sering memasang wheel `py3-none-any` yang murni
    Python: hanya ~1.8x lebih cepat dari difflib, bukan 10x+. Jadi kehadiran
    modul saja TIDAK cukup untuk menyalakan fuzzy di jalur batch.
    """
    global _NATIVE_RAPIDFUZZ
    if _NATIVE_RAPIDFUZZ is None:
        try:
            import rapidfuzz

            base = Path(getattr(rapidfuzz, "__file__", "")).parent
            _NATIVE_RAPIDFUZZ = any(base.rglob("*.so")) or any(base.rglob("*.pyd"))
        except Exception:
            _NATIVE_RAPIDFUZZ = False
    return _NATIVE_RAPIDFUZZ

_NATIVE_RAPIDFUZZ: bool | None = None

def fuzzy_mode(mode: str | None = None) -> str:
    """Mode fuzzy efektif: `auto` -> `on` hanya kalau rapidfuzz native."""
    raw = (mode or os.environ.get(FUZZY_MODE_ENV) or "").strip().lower()
    if raw not in ("auto", "on", "off"):
        raw = DEFAULT_FUZZY_MODE
    if raw == "auto":
        return "on" if have_native_rapidfuzz() else "off"
    return raw

def apply_fuzzy_mode(mode: str | None = None) -> str:
    """Tulis `CS_ENABLE_FUZZY` sesuai mode efektif; kembalikan mode efektif.

    Dipanggil entry point (CLI/menu) SEBELUM engine anak dijalankan supaya
    setelan user ikut terbawa ke subprocess.
    """
    effective = fuzzy_mode(mode)
    os.environ[ENABLE_FUZZY_ENV] = "1" if effective == "on" else "0"
    return effective

class CompatMode(Enum):
    BASELINE = "BASELINE"
    IMPROVED = "IMPROVED"

    @classmethod
    def from_env(cls) -> "CompatMode":
        raw = (os.environ.get("CS_COMPAT") or "").strip().upper()
        try:
            return cls(raw)
        except ValueError:
            return cls.BASELINE


def cluster_mode() -> str:
    raw = (os.environ.get(CLUSTER_MODE_ENV) or "").strip()
    return raw if raw in VALID_CLUSTER_MODES else DEFAULT_CLUSTER_MODE


def dedup_mode() -> str:
    raw = (os.environ.get(DEDUP_MODE_ENV) or "").strip()
    return raw if raw in VALID_DEDUP_MODES else DEFAULT_DEDUP_MODE


def cache_ttl_days() -> int:
    raw = (os.environ.get(CACHE_TTL_DAYS_ENV) or "").strip()
    try:
        val = int(raw)
    except ValueError:
        return DEFAULT_CACHE_TTL_DAYS
    return val if val > 0 else DEFAULT_CACHE_TTL_DAYS


def enable_fuzzy() -> bool:
    """Fuzzy L2/L3 aktif?

    Prioritas: `CS_ENABLE_FUZZY` eksplisit (ditulis `apply_fuzzy_mode`) >
    `CS_FUZZY_MODE` (`auto`/`on`/`off`) > default.
    """
    raw = (os.environ.get(ENABLE_FUZZY_ENV) or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    mode_env = (os.environ.get(FUZZY_MODE_ENV) or "").strip().lower()
    if mode_env in ("auto", "on", "off"):
        return fuzzy_mode(mode_env) == "on"
    return DEFAULT_ENABLE_FUZZY


def fuzzy_threshold() -> float:
    raw = (os.environ.get(FUZZY_THRESHOLD_ENV) or "").strip()
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_FUZZY_THRESHOLD
    return val if 0.0 < val <= 1.0 else DEFAULT_FUZZY_THRESHOLD
