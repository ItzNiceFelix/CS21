"""Registry bahasa. Fase 1: data di-port apa adanya dari `_ALL_KEYWORD_TIERS`.

`load(lang)`:
- mengambil tier dari `spec_data.KEYWORD_TIERS` (fallback `id` seperti baseline),
- menggabung `in` + `te` per tier (dedupe urutan terjaga, bobot dari `in`),
- membangun `LanguageSpec` frozen; `compile()` memanggil kompilasi regex sekali.
"""

from __future__ import annotations

from . import spec_data
from .base import KeywordCore, LanguageSpec, TIER_ORDER, TierWeights

__all__ = ["load", "available", "LanguageSpec", "KeywordCore", "TierWeights", "TIER_ORDER"]

_ALL = spec_data.KEYWORD_TIERS
_DEFAULT_LANG = "id"

# Script per bahasa (dipakai fuzzy/fonetik/fase berikutnya).
_SCRIPTS = {
    "id": "latin",
    "en": "latin",
    "jp": "nonlatin",
    "kr": "nonlatin",
    "in": "nonlatin",
    "th": "nonlatin",
    "te": "nonlatin",
}


def available() -> tuple[str, ...]:
    return tuple(_ALL.keys())


def _tier_names(spec: dict) -> tuple[str, ...]:
    """Tier sesuai urutan data (baseline memakai urutan dict ini)."""
    return tuple(spec.keys())


def _merge_in_te(spec: dict) -> dict:
    """Gabung pattern te ke in per-tier, dedupe urutan terjaga."""
    te = _ALL["te"]
    merged = {}
    for tier_name, data in spec.items():
        in_pats = data.get("patterns", [])
        te_pats = te.get(tier_name, {}).get("patterns", [])
        merged[tier_name] = {
            "bobot": data["bobot"],
            "patterns": list(dict.fromkeys(list(in_pats) + list(te_pats))),
        }
    return merged


def load(lang: str) -> LanguageSpec:
    """Muat `LanguageSpec` terkompilasi untuk `lang` (default id)."""
    raw = _ALL.get(lang, _ALL[_DEFAULT_LANG])
    if lang == "in":
        raw = _merge_in_te(raw)

    default_tiers = _tier_names(_ALL[_DEFAULT_LANG])

    cores = []
    # Tier yang ada di data, lalu pastikan 5 tier inti selalu hadir (key=0).
    for name in list(default_tiers) + [n for n in _tier_names(raw) if n not in default_tiers]:
        data = raw.get(name, {"bobot": TierWeights().as_dict().get(name, 0), "patterns": []})
        if data.get("patterns") is None:
            data = {"bobot": data.get("bobot", 0), "patterns": []}
        cores.append(
            KeywordCore(
                tier=name,
                weight=data["bobot"],
                patterns=tuple(data["patterns"]),
            )
        )

    weights = TierWeights(
        **{k: (raw.get(k, {}).get("bobot", v)) for k, v in TierWeights().as_dict().items()}
    )

    spec = LanguageSpec(
        lang=lang if lang in _ALL else _DEFAULT_LANG,
        transcript_langs=tuple(
            spec_data.TRANSCRIPT_LANGS.get(lang, spec_data.DEFAULT_TRANSCRIPT_LANGS)
        ),
        script=_SCRIPTS.get(lang, "latin"),
        weights=weights,
        cores=tuple(cores),
    )
    return spec.compile()
