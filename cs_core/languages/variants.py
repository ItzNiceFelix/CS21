"""Generator varian keyword (arch §3-§4, P10).

Kamus regex manual dipensiunkan: keyword = data inti + varian yang dihasilkan
programatik (`auto_typo`, `phonetic_id`, `romanize`). Semua fungsi murni
di-cache `functools.lru_cache`.

Aturan:
- `auto_typo`      : substitusi umum kata Latin (c↔k↔j, u↔o, e↔a, collapse
                     dobel, transposisi bersebelahan). Batch — batas `max_variants`.
- `phonetic_id`    : rule table fonetik Indonesia (arch §3.5).
- `romanize`       : JP kana→romaji, KR hangul→RR, Devanagari→IAST, Thai→roman.
                     Bila tak ada map → return form apa adanya.
- `build_regex`    : alternasi `(?:f1|f2|...)`, boundary tepat per script.
- `build_phonetic_set` : set `phonetic_key` untuk lookup L3.

Tabel fonetik SATU karakter besar by design (butuh `max_variants` clamp) →
`_DEFAULT_MAX_VARIANTS`; `phonetic_key` dipakai path L3, bukan ledakan varian.
"""

from __future__ import annotations

import functools
import re

__all__ = [
    "auto_typo",
    "phonetic_key",
    "phonetic_id",
    "romanize",
    "build_regex",
    "build_phonetic_set",
    "CJK_SCRIPTS",
]

# max varian per form sebelum clamp (auto_typo). Cukup untuk typo ASR umum.
_DEFAULT_MAX_VARIANTS = 24

# Script tanpa `\b` word-boundary yang berarti (arch §4.3).
CJK_SCRIPTS = frozenset({"japanese", "korean", "devanagari", "telugu", "thai"})

# ---------------------------------------------------------------------------
# auto_typo
# ---------------------------------------------------------------------------
# Substitusi karakter umum (ekuivalen 1:1). Huruf kecil; input di-fold dulu.
_CHAR_SUBS: dict[str, tuple[str, ...]] = {
    "c": ("k", "s"),
    "k": ("c", "g"),
    "g": ("k", "j"),
    "j": ("g",),
    "s": ("c", "j"),
    "u": ("o",),
    "o": ("u",),
    "e": ("a",),
    "a": ("e",),
    "i": ("e",),
}


def _collapse_doubles(word: str) -> str:
    return re.sub(r"(.)\1+", r"\1", word)


def _uncollapse_vowels(word: str) -> str:
    """Dobel halus: `cegukan`→`ceggukan`? Tidak — gandakan vokal pertama.

    Untuk kata tanpa dobel, buat satu varian dobel konsonan pada konsonan
    interior pertama (umum di ASR Indonesia, mis. `jegukkan`)."""
    for i in range(1, len(word) - 1):
        ch = word[i]
        if ch.isalpha() and ch in "gkjbcptds":
            return word[: i + 1] + ch + word[i + 1 :]
    return word


def _transpositions(word: str) -> list[str]:
    return [word[:i] + word[i + 1] + word[i] + word[i + 2 :] for i in range(len(word) - 1)]


def _typo_batch(form: str, max_variants: int) -> tuple[str, ...]:
    """Batch varian typo untuk form yang sudah di-fold lowercase.

    `max_variants` memotong hasil (deterministik: sorted lalu slice) supaya
    tidak meledak untuk kata panjang.
    """
    base = form.lower()
    out: set[str] = {base}

    # 1) collapse dobel
    cd = _collapse_doubles(base)
    if cd != base:
        out.add(cd)

    # 2) substitusi karakter (satu posisi, satu pengganti)
    for i, ch in enumerate(base):
        for repl in _CHAR_SUBS.get(ch, ()):  # tipe: tuple[str, ...]
            out.add(base[:i] + repl + base[i + 1 :])

    # 3) transposisi bersebelahan (semua posisi, dibatasi panjang)
    if len(base) <= 16:
        out.update(_transpositions(base))

    # 4) satu dobel konsonan interior
    out.add(_uncollapse_vowels(base))

    out.discard(base)
    if len(out) > max_variants:
        ordered = sorted(out)
        out = set(ordered[:max_variants])
    return tuple(sorted(out))


@functools.lru_cache(maxsize=2048)
def _auto_typo_cached(form: str, max_variants: int) -> tuple[str, ...]:
    return _typo_batch(form, max_variants)


def auto_typo(form: str, max_variants: int = _DEFAULT_MAX_VARIANTS) -> set[str]:
    """Varian typo ASR untuk satu kata Latin (tanpa form asal)."""
    if not form:
        return set()
    return set(_auto_typo_cached(form, int(max_variants)))


# ---------------------------------------------------------------------------
# phonetic_id — rule table Indonesia (arch §3.5)
# ---------------------------------------------------------------------------
# Urutan penting: multi-char dulu (ng, nk, ai, ei), baru single char.
_PHONETIC_RULES: tuple[tuple[str, str], ...] = (
    ("ng", "n"),
    ("nk", "n"),
    ("ny", "n"),
    ("ai", "e"),
    ("ei", "e"),
    ("c", "s"),
    ("j", "s"),
    ("s", "s"),
    ("k", "g"),
    ("g", "g"),
    ("b", "p"),
    ("p", "p"),
    ("d", "t"),
    ("t", "t"),
    ("n", "n"),
    ("u", "o"),
    ("o", "o"),
    ("w", "w"),
)


def _phonetic_key(text: str) -> str:
    out = text.lower()
    for src, dst in _PHONETIC_RULES:
        out = out.replace(src, dst)
    return _collapse_doubles(out)


@functools.lru_cache(maxsize=4096)
def phonetic_key(word: str) -> str:
    """Kunci kanonik fonetik Indonesia (arch §3.5).

    `phonetic_key("cegukan") == phonetic_key("jegukan") == phonetic_key("segukan")`.
    """
    if not word:
        return ""
    return _phonetic_key(word)


def phonetic_id(form: str) -> str:
    """Alias `phonetic_key` (nama di plan T2.1)."""
    return phonetic_key(form)


# ---------------------------------------------------------------------------
# romanize — map statis kecil (JP/KR/Devanagari/Thai → Latin)
# ---------------------------------------------------------------------------
_JP_ROMAJI: tuple[tuple[str, str], ...] = (
    ("しゃっ","shak"), ("シャッ","shak"), ("しゃ","sha"), ("シャ","sha"),
    ("しゅ","shu"), ("シュ","shu"), ("しょ","sho"), ("ショ","sho"),
    ("く","ku"), ("ク","ku"), ("か","ka"), ("カ","ka"),
    ("き","ki"), ("キ","ki"), ("け","ke"), ("ケ","ke"), ("こ","ko"), ("コ","ko"),
    ("っ","t"), ("ッ","t"),
    ("り","ri"), ("リ","ri"), ("り","ri"),
    ("ひ","hi"), ("ヒ","hi"),
    ("ん","n"), ("ン","n"),
    ("び","bi"), ("ビ","bi"),
    ("が","ga"), ("ガ","ga"), ("ま","ma"), ("マ","ma"),
    ("す","su"), ("ス","su"),
)

_KR_ROMAN: tuple[tuple[str, str], ...] = (
    ("딸꾹질", "ttalkkukjil"),
    ("딸꾹", "ttalkkuk"),
    ("딸각", "ttalgak"),
    ("딸깍", "ttalkkak"),
    ("딸구질", "ttalgujil"),
    ("딸국", "ttalguk"),
    ("사레", "sare"),
    ("캑캑", "kyayngkyayng"),
    ("컥컥", "keokkeok"),
)

_HI_IAST: tuple[tuple[str, str], ...] = (
    ("हिचकी", "hichki"),
    ("इचकी", "ichaki"),
    ("हिचकि", "hichaki"),
    ("हिचकियाँ", "hichakiyan"),
    ("हिचकिया", "hichakiya"),
    ("हिचकीं", "hichakin"),
    ("ह", "h"), ("ि", "i"),
)

_TH_ROMAN: tuple[tuple[str, str], ...] = (
    ("สะอึก", "sauek"),
    ("สอึก", "sauek"),
    ("สะอิก", "sauek"),
    ("สำลัก", "samlak"),
    ("เรอ", "roe"),
)

_ROMAN_MAPS: dict[str, tuple[tuple[str, str], ...]] = {
    "japanese": _JP_ROMAJI,
    "korean": _KR_ROMAN,
    "devanagari": _HI_IAST,
    "thai": _TH_ROMAN,
}

# romanizable per skrip (Latin tak perlu).
_SCRIPTS_WITH_ROMAN = frozenset(_ROMAN_MAPS)


@functools.lru_cache(maxsize=2048)
def _romanize_cached(form: str, script: str) -> str:
    table = _ROMAN_MAPS.get(script)
    if not table:
        return form
    out = form
    for src, dst in table:
        out = out.replace(src, dst)
    return out


def romanize(form: str, script: str) -> str:
    """Romanisasi sederhana `form` untuk `script` (arch §4.3).

    Bila skrip tak punya map → return `form` apa adanya.
    """
    if not form:
        return form
    return _romanize_cached(form, script)


# ---------------------------------------------------------------------------
# build_regex / build_phonetic_set
# ---------------------------------------------------------------------------
def build_regex(forms, script: str = "latin") -> str:
    """Alternasi `(?:f1|f2|...)` dengan boundary tepat per script.

    - Latin    : `\\b(?:...)\\b`
    - non-Latin: `(?:...)` tanpa `\\b` (CJK/Devanagari/Telugu/Thai tak punya
      batas kata yang berguna).
    - Bila form mengandung marker literal `*` (mis. `*hic*`) → TANPA `\\b`
      (baseline memakai `\\*hic\\*`, bukan `\\b\\*hic\\*\\b`).
    """
    pats = [p for p in dict.fromkeys(forms) if p]
    if not pats:
        return r"(?!)"
    body = "(?:" + "|".join(pats) + ")"
    if script in CJK_SCRIPTS or any("*" in p for p in pats):
        return body
    return r"\b" + body + r"\b"


def build_phonetic_set(forms) -> frozenset[str]:
    """Set `phonetic_key` dari daftar form (lookup L3)."""
    return frozenset(phonetic_key(f) for f in forms if f)
