"""Matching L1 (exact/regex). Fuzzy/phonetic menyusul Fase 3.

`classify_tiers` meniru `classify_text` lama: untuk setiap tier, hitung
jumlah pattern yang match (satu pattern = +1, walaupun muncul berkali-kali),
bukan jumlah occurrence.
"""

from __future__ import annotations

import re

from .languages.base import KeywordCore, LanguageSpec
from .tokens import TokenList

__all__ = ["count_rule_hits", "classify_tiers"]


def count_rule_hits(toks: TokenList, rules, text: str) -> int:
    """L1 exact/regex: jumlah rule yang match.

    `rules` boleh `KeywordCore`, `LanguageSpec`, atau iterable pattern.
    Fase 1: 1 = ada rule match, 0 = tidak. (Mengikuti semantik `classify_text`.)
    """
    if isinstance(rules, KeywordCore):
        pats = rules.regexes or ()
    elif isinstance(rules, LanguageSpec):
        pats = tuple(p for c in rules.cores for p in (c.regexes or ()))
    else:
        pats = tuple(rules)
    for pat in pats:
        if isinstance(pat, re.Pattern):
            if pat.search(text):
                return 1
        elif re.search(pat, text):
            return 1
    return 0


def classify_tiers(text: str, spec: LanguageSpec) -> dict[str, int]:
    """Hitung jumlah pattern yang match per tier (semua tier selalu hadir)."""
    result = {c.tier: 0 for c in spec.cores}
    for core in spec.cores:
        for pat in core.regexes or ():
            if pat.search(text):
                result[core.tier] += 1
    return result
