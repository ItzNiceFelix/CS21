"""Config runtime cs_core. Semua dari env, default aman untuk BASELINE.

- `CompatMode`: env `CS_COMPAT` (default `BASELINE`).
- `CLUSTER_MODE`: `video_duration` (default) | `hit_span`.
- `DEDUP_MODE`: `float` | `int0`.
- `CACHE_TTL_DAYS`: default 30.
- `CS_ENABLE_FUZZY`: `1` (default) | `0` — matikan L2/L3 = perilaku Fase 1.
- `CS_FUZZY_THRESHOLD`: ambang default bila tier tak mendeklarasikan.
"""

from __future__ import annotations

import os
from enum import Enum

__all__ = [
    "CompatMode",
    "CLUSTER_MODE_ENV",
    "DEDUP_MODE_ENV",
    "CACHE_TTL_DAYS_ENV",
    "ENABLE_FUZZY_ENV",
    "FUZZY_THRESHOLD_ENV",
    "DEFAULT_FUZZY_THRESHOLD",
    "DEFAULT_FUZZY_HITS_CAP",
    "cluster_mode",
    "dedup_mode",
    "cache_ttl_days",
    "enable_fuzzy",
    "fuzzy_threshold",
]

CLUSTER_MODE_ENV = "CLUSTER_MODE"
DEDUP_MODE_ENV = "DEDUP_MODE"
CACHE_TTL_DAYS_ENV = "CACHE_TTL_DAYS"
ENABLE_FUZZY_ENV = "CS_ENABLE_FUZZY"
FUZZY_THRESHOLD_ENV = "CS_FUZZY_THRESHOLD"

VALID_CLUSTER_MODES = ("video_duration", "hit_span")
VALID_DEDUP_MODES = ("float", "int0")
DEFAULT_CLUSTER_MODE = "video_duration"
DEFAULT_DEDUP_MODE = "float"
DEFAULT_CACHE_TTL_DAYS = 30
DEFAULT_ENABLE_FUZZY = True
# Ambang tingkat bahasa (tier boleh override di forms.py).
DEFAULT_FUZZY_THRESHOLD = 0.85


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
    """`CS_ENABLE_FUZZY`: "0"/"false"/"no" -> False; default True."""
    raw = (os.environ.get(ENABLE_FUZZY_ENV) or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return DEFAULT_ENABLE_FUZZY


def fuzzy_threshold() -> float:
    raw = (os.environ.get(FUZZY_THRESHOLD_ENV) or "").strip()
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_FUZZY_THRESHOLD
    return val if 0.0 < val <= 1.0 else DEFAULT_FUZZY_THRESHOLD
