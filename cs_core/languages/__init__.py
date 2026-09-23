"""Registry bahasa — bangun `LanguageSpec` dari deklarasi `forms.FORMS`.

`load(lang)`:
- ambil deklarasi bentuk dari `forms.FORMS` (fallback `id` seperti baseline),
- merge Telugu ke `in` per-tier (arch §4.4, dedupe urutan terjaga),
- generate varian (`auto_typo`/`phonetic_id`/`romanized`) + regex via
  `variants.build_regex`, gabung `core_forms` + `regex` + varian,
- `compile()` sekali (regex + prefilter) — tidak ada global mutable.

`spec_data.KEYWORD_TIERS` tetap baseline referensi (dibaca `tools/diff_forms.py`).
"""

from __future__ import annotations

from . import forms as _forms
from .base import (
    DEFAULT_FUZZY_THRESHOLD,
    KeywordCore,
    LanguageSpec,
    TIER_ORDER,
    TierWeights,
)
from .variants import auto_typo, build_regex, phonetic_id, romanize

__all__ = ["load", "available", "LanguageSpec", "KeywordCore", "TierWeights", "TIER_ORDER"]

_DEFAULT_LANG = "id"
_ALL = _forms.FORMS

# tier -> script yang memakai romanisasi untuk bentuk Latin TYPO.
_SCRIPTS = _forms.SCRIPTS


def available() -> tuple[str, ...]:
    return tuple(_ALL.keys())


def _tier_names(raw: dict) -> tuple[str, ...]:
    return tuple(raw.get("tiers", {}).keys())


def _merge_in_te(raw: dict) -> dict:
    """Gabung core_forms/regex/romanized `te` ke `in` per-tier, dedupe terjaga."""
    te = _ALL.get("te", {}).get("tiers", {})
    tiers = {}
    for name, data in raw.get("tiers", {}).items():
        te_data = te.get(name, {})
        merged = dict(data)
        for key in ("core_forms", "regex", "romanized", "variants"):
            merged[key] = list(
                dict.fromkeys(list(data.get(key, [])) + list(te_data.get(key, [])))
            )
        tiers[name] = merged
    out = dict(raw)
    out["tiers"] = tiers
    return out


def _expand_forms(data: dict, script: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Kembalikan (core_forms, patterns) untuk satu tier dari deklarasi."""
    core_forms = list(data.get("core_forms", []))

    literal_forms = list(core_forms)
    gen_variants: set[str] = set()
    if "auto_typo" in data.get("variants", []):
        cap = int(data.get("max_variants", 24))
        for form in literal_forms:
            if form.isascii() and form.isalpha():
                gen_variants |= auto_typo(form, cap)
    if "phonetic_id" in data.get("variants", []):
        # fonetik ID = lookup L3 (arch §3.1), bukan pattern regex — hanya
        # menyumbang ke pattern bila ekuivalennya berupa kata Latin.
        for form in literal_forms:
            if form.isascii() and form.isalpha():
                key = phonetic_id(form)
                if key and key != form.lower():
                    gen_variants.add(key)

    romanized = [romanize(f, script) for f in data.get("romanized", [])]
    latin_forms = sorted(
        {f for f in (list(gen_variants) + romanized) if f and f.isascii()}
    )

    patterns: list[str] = []
    if core_forms:
        patterns.append(build_regex(core_forms, script))
    if latin_forms:
        patterns.append(build_regex(latin_forms, "latin"))
    patterns.extend(data.get("regex", []))
    return tuple(core_forms), tuple(patterns)


def load(lang: str) -> LanguageSpec:
    """Muat `LanguageSpec` terkompilasi untuk `lang` (default id)."""
    key = lang if lang in _ALL else _DEFAULT_LANG
    raw = dict(_ALL[key])
    if key == "in":
        raw = _merge_in_te(raw)

    script = raw.get("script", _SCRIPTS.get(key, "latin"))
    tiers = raw.get("tiers", {})

    cores: list[KeywordCore] = []
    fuzzy_skip: set[str] = set()
    thresholds: dict[str, float] = {}
    for name in TIER_ORDER:
        data = tiers.get(name, {})
        _core_forms, patterns = _expand_forms(data, script)
        weight = int(data.get("weight", TierWeights().as_dict().get(name, 0)))
        cores.append(
            KeywordCore(
                tier=name,
                weight=weight,
                patterns=patterns,
                core_forms=tuple(data.get("core_forms", [])),
                neg_context=tuple(data.get("neg_context", [])),
                fuzzy_skip=frozenset(data.get("fuzzy_skip", [])),
                fuzzy_threshold=float(
                    data.get("fuzzy_threshold", DEFAULT_FUZZY_THRESHOLD)
                ),
            )
        )
        fuzzy_skip.update(data.get("fuzzy_skip", []))
        if "fuzzy_threshold" in data:
            thresholds[name] = float(data["fuzzy_threshold"])

    weights = TierWeights(
        **{k: int(tiers.get(k, {}).get("weight", v)) for k, v in TierWeights().as_dict().items()}
    )

    spec = LanguageSpec(
        lang=key,
        transcript_langs=tuple(
            _forms.TRANSCRIPT_LANGS.get(lang, _forms.DEFAULT_TRANSCRIPT_LANGS)
        ),
        script=script,
        weights=weights,
        cores=tuple(cores),
        neg_context=tuple(
            dict.fromkeys(list(raw.get("neg_context_global", []))
                          + [c for t in tiers.values() for c in t.get("neg_context", [])])
        ),
        fuzzy_skip=frozenset(fuzzy_skip),
        fuzzy_threshold=thresholds,
        fuzzy_hits_cap=int(raw.get("fuzzy_hits_cap", 8)),
    )
    return spec.compile()
