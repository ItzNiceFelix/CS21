"""Config runtime cs_core. Semua dari env, default aman untuk BASELINE.

- `CompatMode`: env `CS_COMPAT` (default `BASELINE`).
- `CLUSTER_MODE`: `video_duration` (default) | `hit_span`.
- `DEDUP_MODE`: `float` | `int0`.
- `CACHE_TTL_DAYS`: default 30.
"""

from __future__ import annotations

import os
from enum import Enum

__all__ = [
    "CompatMode",
    "CLUSTER_MODE_ENV",
    "DEDUP_MODE_ENV",
    "CACHE_TTL_DAYS_ENV",
    "cluster_mode",
    "dedup_mode",
    "cache_ttl_days",
]

CLUSTER_MODE_ENV = "CLUSTER_MODE"
DEDUP_MODE_ENV = "DEDUP_MODE"
CACHE_TTL_DAYS_ENV = "CACHE_TTL_DAYS"

VALID_CLUSTER_MODES = ("video_duration", "hit_span")
VALID_DEDUP_MODES = ("float", "int0")
DEFAULT_CLUSTER_MODE = "video_duration"
DEFAULT_DEDUP_MODE = "float"
DEFAULT_CACHE_TTL_DAYS = 30


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
