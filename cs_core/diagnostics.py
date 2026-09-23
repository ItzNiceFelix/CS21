"""Diagnostik ringan: probe RapidFuzz, fallback status, timing. TANPA rich.

`HAVE_RAPIDFUZZ` di-probe SEKALI saat import (lazy: tak ada import berat di
startup sel, hanya try/except). Test fallback boleh monkeypatch atribut ini di
`cs_core.diagnostics` — `matching` membacanya lewat helper `_has_rapidfuzz()`
agar patch terlihat (lihat T3.2/T3.5).
"""

from __future__ import annotations

import time

__all__ = [
    "HAVE_RAPIDFUZZ",
    "HAVE_DIFFLIB",
    "fallback_status",
    "Timer",
]


def _probe_rapidfuzz() -> bool:
    try:
        import rapidfuzz  # noqa: F401
    except Exception:
        return False
    return True


# Probe runtime (stdlib selalu ada; rapidfuzz opsional).
HAVE_RAPIDFUZZ: bool = _probe_rapidfuzz()
HAVE_DIFFLIB: bool = True  # difflib selalu ada (fallback wajib).


def fallback_status() -> dict:
    """Ringkasan status dependency fuzzy untuk CLI/HTML.

    `engine`: jalur yang dipakai `matching.fuzzy_match_token`.
        "rapidfuzz" bila ada, else "difflib".
    """
    return {
        "rapidfuzz": HAVE_RAPIDFUZZ,
        "difflib": HAVE_DIFFLIB,
        "engine": "rapidfuzz" if HAVE_RAPIDFUZZ else "difflib",
        "degraded": not HAVE_RAPIDFUZZ,
    }


class Timer:
    """Timing ringan (tanpa rich). Pakai sebagai context manager.

    >>> with Timer() as t:
    ...     pass
    >>> t.elapsed_ms >= 0
    True
    """

    __slots__ = ("_start", "elapsed_ms")

    def __init__(self):
        self._start = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> bool:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        return False
