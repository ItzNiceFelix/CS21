"""Struktur bahasa: `LanguageSpec`, `KeywordCore`, `TierWeights`.

Semua frozen + immutable. Regex dikompilasi SEKALI di `compile()` dan disimpan
di objek — tidak ada global mutable seperti `_init_lang` (aman ThreadPool).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

__all__ = ["KeywordCore", "TierWeights", "LanguageSpec", "TIER_ORDER", "DEFAULT_FUZZY_THRESHOLD"]

# Urutan kasta/tampilan tier — sama dengan baseline.
TIER_ORDER = ("CORE", "TYPO", "SILENT", "CONTEXT", "FP")

# Ambang fuzzy default (dipakai bila tier tak mendeklarasikan sendiri).
DEFAULT_FUZZY_THRESHOLD = 0.85


@dataclass(frozen=True)
class TierWeights:
    CORE: int = 5
    TYPO: int = 4
    SILENT: int = 4
    CONTEXT: int = 2
    FP: int = 1

    def as_dict(self) -> dict:
        return {
            "CORE": self.CORE,
            "TYPO": self.TYPO,
            "SILENT": self.SILENT,
            "CONTEXT": self.CONTEXT,
            "FP": self.FP,
        }


@dataclass(frozen=True)
class KeywordCore:
    """Pattern mentah satu tier. `patterns` sudah bebas `(?!)` (P4)."""

    tier: str
    weight: int
    patterns: tuple[str, ...] = ()
    regexes: tuple[re.Pattern, ...] | None = None
    core_forms: tuple[str, ...] = ()
    neg_context: tuple[str, ...] = ()
    fuzzy_skip: frozenset[str] = frozenset()
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD

    def compile(self, flags: int = re.IGNORECASE) -> tuple[re.Pattern, ...]:
        out = []
        for pat in self.patterns:
            try:
                out.append(re.compile(pat, flags))
            except re.error:
                # Baseline menelan re.error diam-diam (E460-461, arch §8).
                pass
        return tuple(out)


@dataclass(frozen=True)
class LanguageSpec:
    lang: str
    transcript_langs: tuple[str, ...]
    script: str  # "latin" | "japanese" | "korean" | "devanagari" | "telugu" | "thai"
    weights: TierWeights
    cores: tuple[KeywordCore, ...]
    combined_prefilter: re.Pattern | None = None
    # Fase 3 — anti-FP berlapis. Default aman bila kosong.
    neg_context: tuple[str, ...] = ()
    fuzzy_skip: frozenset[str] = frozenset()
    fuzzy_threshold: dict[str, float] = None  # tier -> ambang overrides
    fuzzy_hits_cap: int = 8

    def __post_init__(self):
        # dataclass frozen: normalisasi default mutable -> default immutable.
        if self.fuzzy_threshold is None or not isinstance(self.fuzzy_threshold, dict):
            object.__setattr__(self, "fuzzy_threshold", {})
        if not isinstance(self.neg_context, tuple):
            object.__setattr__(self, "neg_context", tuple(self.neg_context))
        if not isinstance(self.fuzzy_skip, frozenset):
            object.__setattr__(self, "fuzzy_skip", frozenset(self.fuzzy_skip))

    # --- lookup cepat -------------------------------------------------
    def core_for(self, tier: str) -> KeywordCore | None:
        for c in self.cores:
            if c.tier == tier:
                return c
        return None

    def tier_names(self) -> tuple[str, ...]:
        return tuple(c.tier for c in self.cores)

    # --- kompilasi sekali ---------------------------------------------
    def compile(self) -> "LanguageSpec":
        """Kompilasi semua regex + prefilter dan simpan ke objek baru.

        Idempoten: `compile()` pada spec yang sudah terkompilasi hanya
        mengembalikan dirinya.
        """
        if all(c.regexes is not None for c in self.cores):
            return self
        cores = tuple(
            replace(c, regexes=c.compile()) for c in self.cores
        )
        prefilter = _combine_prefilter(cores)
        return replace(self, cores=cores, combined_prefilter=prefilter)


def _combine_prefilter(cores: tuple[KeywordCore, ...]) -> re.Pattern:
    """Gabungan semua pattern non-kosong, seperti ALL_PATTERNS_COMBINED."""
    pats = [p for c in cores for p in c.patterns]
    joined = "|".join(pats) if pats else r"(?!)"
    try:
        return re.compile(joined, re.IGNORECASE)
    except re.error:
        return re.compile(r"(?!)")
