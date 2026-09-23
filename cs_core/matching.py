"""Matching berlapis: L1 exact/regex → L2 fuzzy token → L3 phonetic-rule.

- `classify_tiers`: helper L1 exact per tier. Dipakai test anti-typo
  (`tests/test_anti_typo.py`); production memakai `scoring._exact_tier_counts`.
- `fuzzy_match_token`: rapidfuzz `process.extractOne` bila ada, else
  `difflib.SequenceMatcher` + length gate (arch §5.3).
- `phonetic_hit`: lookup `phonetic_key(token)` di set fonetik (L3).
- `neg_context_hit`: cek ±jendela token di sekitar match (arch §3.3 #2).
- `match_segment`: orkestrasi L1→L2→L3 per tier dengan short-circuit,
  `fuzzy_skip`, `fuzzy_threshold` per tier, dan `neg_context` (turun tier).

Aturan emas anti-FP (arch §3.3): L1 selalu menang; fuzzy hanya MENAMBAH
deteksi tier yang L1-nya kosong, tidak pernah mengubah hit exact.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from . import diagnostics as _diag
from .languages.base import DEFAULT_FUZZY_THRESHOLD, KeywordCore, LanguageSpec
from .languages.variants import phonetic_key
from .tokens import extract

__all__ = [
    "classify_tiers",
    "fuzzy_match_token",
    "phonetic_hit",
    "neg_context_hit",
    "match_segment",
]

# Jendela negatif: ±2 token default (arch §3.3 #2).
NEG_CONTEXT_WINDOW = 2
# Panjang minimum token untuk fuzzy (hindari `hic`/`bhi` nyasar).
MIN_FUZZY_LEN = 4
# Batas form kandidat yang dianggap masuk akal (anti-ledakan).
MAX_FUZZY_CAND_LEN = 24


def _has_rapidfuzz() -> bool:
    """Baca probe lewat modul diagnostics agar monkeypatch test terlihat."""
    return bool(getattr(_diag, "HAVE_RAPIDFUZZ", False))


# ---------------------------------------------------------------------------
# L1 — exact/regex (Fase 1, tidak berubah)
# ---------------------------------------------------------------------------
def classify_tiers(text: str, spec: LanguageSpec) -> dict[str, int]:
    """Hitung jumlah pattern yang match per tier (semua tier selalu hadir).

    Helper/test-only: production scoring memakai `scoring._exact_tier_counts`
    (logika sama). Dipertahankan karena `tests/test_anti_typo.py` memakainya.
    """
    result = {c.tier: 0 for c in spec.cores}
    for core in spec.cores:
        for pat in core.regexes or ():
            if pat.search(text):
                result[core.tier] += 1
    return result


# ---------------------------------------------------------------------------
# L2 — fuzzy token
# ---------------------------------------------------------------------------
def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _extract_one_difflib(key: str, candidates, threshold: float):
    """Fallback `process.extractOne` dengan length gate (arch §5.3).

    Length gate: `abs(len(key) - len(cand)) <= max_edit` di mana
    `max_edit = ceil((1 - threshold) * max_len)`. Ini membuang pasangan token
    yang jelas beda panjang SEBELUM `SequenceMatcher` (hindari O(n²) liar).
    """
    best = None
    best_score = threshold
    max_len = max(len(key), max(len(c) for c in candidates))
    # ceil((1-threshold)*max_len) tanpa `math.ceil`: int() aman karena +1.
    max_edit = max(1, int((1.0 - threshold) * max_len) + 1)
    for cand in candidates:
        if abs(len(key) - len(cand)) > max_edit:
            continue
        score = _ratio(key, cand)
        if score >= best_score:
            best_score = score
            best = cand
    return best


def _extract_one_rapidfuzz(key: str, candidates, threshold: float):
    """`rapidfuzz.process.extractOne` bila tersedia, else None."""
    try:
        from rapidfuzz import fuzz, process
    except Exception:
        return None
    try:
        match = process.extractOne(key, candidates, scorer=fuzz.ratio, score_cutoff=threshold * 100)
    except Exception:
        return None
    if not match:
        return None
    return match[0]


def fuzzy_match_token(key: str, candidates, threshold: float) -> bool:
    """True bila `key` mirip salah satu `candidates` di atas `threshold` (0..1)."""
    if not key or threshold <= 0.0:
        return False
    cands = [c for c in candidates if c]
    if not cands:
        return False
    if _has_rapidfuzz():
        hit = _extract_one_rapidfuzz(key, cands, threshold)
        if hit is not None:
            return True
        # rapidfuzz ada tapi error → tetap coba difflib (jangan diam).
    hit = _extract_one_difflib(key, cands, threshold)
    return hit is not None


# ---------------------------------------------------------------------------
# L3 — phonetic-rule
# ---------------------------------------------------------------------------
def phonetic_hit(token: str, phonetic_set) -> bool:
    """True bila `phonetic_key(token)` ada di `phonetic_set` (L3)."""
    if not token or not phonetic_set:
        return False
    key = phonetic_key(token.lower())
    return bool(key) and key in phonetic_set


# ---------------------------------------------------------------------------
# Negative context
# ---------------------------------------------------------------------------
def neg_context_hit(text: str, spans, neg_terms, window: int = NEG_CONTEXT_WINDOW) -> bool:
    """True bila `neg_terms` muncul di ±`window` token sekitar salah satu span.

    `spans` = iterable `(start, end)` offset karakter match. Negatif dicek pada
    teks yang sama (normalisasi ringan tak diubah). Term boleh frasa multi-kata;
    fallback ke substring sederhana bila term bukan satu token penuh.
    """
    if not neg_terms:
        return False
    toks = extract(text).tokens
    if not toks:
        return False
    neg = [t.lower() for t in neg_terms if t]
    if not neg:
        return False
    for start, _end in spans:
        idx = None
        for i, tok in enumerate(toks):
            if tok.start <= start < tok.end:
                idx = i
                break
        if idx is None:
            for i, tok in enumerate(toks):
                if tok.start >= start:
                    idx = i
                    break
        if idx is None:
            idx = len(toks) - 1
        lo = max(0, idx - window)
        hi = min(len(toks), idx + window + 1)
        window_tokens = {toks[j].raw.lower() for j in range(lo, hi)}
        for term in neg:
            if term in window_tokens:
                return True
            # term frasa (mis. "economic hiccup") → cek substring teks di jendela
            if len(term.split()) > 1 and term in text.lower():
                return True
    return False


# ---------------------------------------------------------------------------
# Orkestrasi tingkat tinggi
# ---------------------------------------------------------------------------
def _candidates_for(core: KeywordCore) -> list[str]:
    """Kandidat token fuzzy HANYA dari `core_forms` deklaratif.

    Pattern regex bersifat struktural (frasa/`[uo]`/`\\b`) sengaja TIDAK
    dipecah jadi kata: melakukannya menarik kata umum (`minor`, `stop`) dan
    memicu FP tier. Kata inti sudah tersedia di `core_forms` (forms.py).
    """
    return sorted(
        {
            f.lower()
            for f in (core.core_forms or ())
            if f.isascii() and f.isalpha() and len(f) <= MAX_FUZZY_CAND_LEN
        }
    )


def _phonetic_set_for(core: KeywordCore) -> frozenset[str]:
    forms = [f.lower() for f in (core.core_forms or ()) if f.isascii() and f.isalpha()]
    return frozenset(phonetic_key(f) for f in forms)


def _rules_hit(core: KeywordCore, text: str) -> bool:
    for pat in core.regexes or ():
        if pat.search(text):
            return True
    return False


def match_segment(text: str, spec: LanguageSpec, *, enable_fuzzy: bool = True) -> dict[str, int]:
    """Klasifikasi satu segmen lintas lapis (L1→L2→L3) dengan short-circuit.

    Kembalian: `{tier: 0|1}` untuk semua tier `spec` (0/1 karena konsumen
    scoring menghitung `>0`; hitung per-tier = 1 kontribusi per segmen).

    - L1 exact: bila tier match → tier=1, TIDAK fuzzy.
    - L2 fuzzy token: hanya untuk tier yang L1 kosong; token yang match exact
      tidak difuzzy (short-circuit `match_segment`), `fuzzy_skip` dilewati,
      ambang per-tier (`keyword.fuzzy_threshold` / spec override).
    - L3 phonetic: hanya script Latin, hanya bila L1+L2 tier kosong.
    - `neg_context`: bila match fuzzy kena konteks negatif → tier diturunkan
      ke TYPO bila ada, else di-suppress (0).
    """
    out = {c.tier: 0 for c in spec.cores}
    if not text:
        return out

    toks = extract(text)
    token_norms = [t.raw.lower() for t in toks.tokens]
    script_latin = spec.script == "latin"
    spec_skip = spec.fuzzy_skip or frozenset()

    # Token yang sudah diklaim EXACT oleh tier mana pun tidak boleh jadi
    # kandidat fuzzy tier lain. Contoh: "cegukan" exact-match CORE; token yang
    # sama tidak boleh lalu di-fuzzy ke form TYPO ("jegukan"/"segukan") dan
    # menambah TYPO — itu menaikkan skor di luar baseline (aturan emas arch
    # §3.3: L1 selalu menang, fuzzy hanya mengisi tier yang L1-nya kosong).
    claimed: set[str] = set()
    for core in spec.cores:
        for tok in token_norms:
            if tok in claimed:
                continue
            if _rules_hit(core, tok):
                claimed.add(tok)

    for core in spec.cores:
        tier = core.tier
        # ── L1 exact ────────────────────────────────────────────────
        if _rules_hit(core, text):
            out[tier] = 1
            continue

        if not enable_fuzzy:
            # Fase 1 (non-fuzzy): L1 saja — perilaku identik byte-for-byte.
            continue

        # ── L2 fuzzy token ──────────────────────────────────────────
        threshold = spec.fuzzy_threshold.get(tier, core.fuzzy_threshold)
        if not isinstance(threshold, (int, float)):
            threshold = DEFAULT_FUZZY_THRESHOLD
        cands = _candidates_for(core)
        fuzzy_ok = False
        if cands:
            for tok in token_norms:
                if len(tok) < MIN_FUZZY_LEN or not tok.isascii() or not tok.isalpha():
                    continue
                if tok in spec_skip or tok in (core.fuzzy_skip or ()):
                    continue
                if tok in claimed:
                    continue  # sudah exact-match tier lain (mis. CORE)
                if fuzzy_match_token(tok, cands, float(threshold)):
                    fuzzy_ok = True
                    break

        # ── L3 phonetic ─────────────────────────────────────────────
        if not fuzzy_ok and script_latin:
            pset = _phonetic_set_for(core)
            if pset:
                for tok in token_norms:
                    if tok in spec_skip or tok in (core.fuzzy_skip or ()):
                        continue
                    if tok in claimed:
                        continue  # sudah exact-match tier lain
                    if len(tok) >= MIN_FUZZY_LEN and tok.isalpha() and tok.isascii() \
                            and phonetic_hit(tok, pset):
                        fuzzy_ok = True
                        break

        if not fuzzy_ok:
            continue

        # ── Anti-FP: neg_context ────────────────────────────────────
        neg = tuple(core.neg_context) + tuple(spec.neg_context)
        if neg and neg_context_hit(text, _match_spans(text), neg):
            if tier == "CORE" and _has_tier(spec, "TYPO"):
                out["TYPO"] = 1  # turunkan CORE→TYPO (arch §3.3 #2)
            continue
        out[tier] = 1

    return out


def _has_tier(spec: LanguageSpec, tier: str) -> bool:
    return any(c.tier == tier for c in spec.cores)


def _match_spans(text: str) -> list[tuple[int, int]]:
    """Span seluruh token teks untuk `neg_context_hit`.

    Fuzzy dikonfirmasi di segmen yang sama, jadi jendela ±2 token di sekitar
    token mana pun sudah cukup (tanpa offset match presisi).
    """
    return [(t.start, t.end) for t in extract(text).tokens]
