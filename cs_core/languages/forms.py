"""Deklarasi bentuk per bahasa (arch §4.1) — keyword = data.

`spec_data.KEYWORD_TIERS` tetap ada sebagai **baseline referensi** (legacy);
`tools/diff_forms.py` membandingkan deklarasi di sini terhadap baseline untuk
memastikan tidak ada form CORE lama yang hilang (P10).

Bentuk deklarasi per tier:
    "CORE": {
        "weight": 5,
        "core_forms": [...],        # kata inti (exact)
        "regex": [...],             # pattern struktur (opsional)
        "variants": ["auto_typo", "phonetic_id"],
        "max_variants": 24,         # clamp auto_typo (opsional)
    }

Non-Latin (jp/kr/in/th/te) TIDAK memakai phonetic Inggris (arch §3.4); cukup
exact form + `romanized` untuk bentuk Latin TYPO.
"""

from __future__ import annotations

__all__ = ["FORMS", "DEFAULT_WEIGHTS", "SCRIPTS", "TRANSCRIPT_LANGS"]

DEFAULT_WEIGHTS = {"CORE": 5, "TYPO": 4, "SILENT": 4, "CONTEXT": 2, "FP": 1}

SCRIPTS = {
    "id": "latin",
    "en": "latin",
    "jp": "japanese",
    "kr": "korean",
    "in": "devanagari",
    "th": "thai",
    "te": "telugu",
}

# P9: `te` internal; map transcript eksplisit (te,te-IN,hi).
TRANSCRIPT_LANGS = {
    "id": ["id", "en", "id-ID"],
    "en": ["en", "en-US", "en-GB"],
    "jp": ["ja", "ja-JP"],
    "kr": ["ko", "ko-KR"],
    "in": ["hi", "hi-IN", "te", "te-IN"],
    "th": ["th", "th-TH"],
    "te": ["te", "te-IN", "hi"],
}
DEFAULT_TRANSCRIPT_LANGS = ["id", "en", "id-ID"]


def _tier(weight, *, core_forms=(), regex=(), romanized=(), variants=(),
          max_variants=None, compounds=(), context_forms=(), patterns=(),
          neg_context=(), fuzzy_skip=(), fuzzy_threshold=None):
    d = {
        "weight": weight,
        "core_forms": list(core_forms),
        "regex": list(regex),
        "romanized": list(romanized),
        "variants": list(variants),
        "compounds": list(compounds),
        "context_forms": list(context_forms),
        "patterns": list(patterns),
        "neg_context": list(neg_context),
        "fuzzy_skip": list(fuzzy_skip),
    }
    if max_variants is not None:
        d["max_variants"] = max_variants
    if fuzzy_threshold is not None:
        d["fuzzy_threshold"] = fuzzy_threshold
    return d


FORMS: dict[str, dict] = {
    # =====================================================================
    # INDONESIA — paling detail (arch §4.1 + spec §2.1)
    # =====================================================================
    "id": {
        "script": "latin",
        "tiers": {
            "CORE": _tier(
                5,
                # cegukan + suffix + aksen
                core_forms=["cegukan", "cegukannya", "cegukanku", "kecegukan", "kecegukan"],
                # varian struktur (port regex spec §2.1, `(?!)` dihapus P4)
                regex=[
                    "ce+g+[uo]+k+[ae]+n+",
                    "ce+g+[uo]+k+[ae]+n+nya",
                    "ce+g+[uo]+k+[ae]+n+ku",
                    "ce+c+e+g+[uo]+k+[ae]+n+",
                    "ce+k+[uo]+k+[ae]+n+",
                    "ce+k+[uo]+k+[ae]+n+nya",
                    "ce+k+[uo]+k+[ae]+n+ku",
                    "je+g+[uo]+k+[ae]+n+",
                    "ke+je+g+[uo]+k+[ae]+n+",
                    "ce+g+[uo]+k+e+n+",
                    "ce+k+[uo]+k+e+n+",
                    "\\*hi+k+\\*",
                    "\\*hi+c+\\*",
                    "\\*ngi+k+\\*",
                ],
                # CORE TIDAK memakai auto_typo/phonetic: regex manual di atas sudah
                # menangani varian ejaan; auto_typo di CORE over-generate (mis.
                # menghasilkan "cekukan"/"segukan" yang justru TYPO) -> FP + skor naik.
                compounds=["*hik*", "*hic*", "*ngik*"],
                fuzzy_threshold=0.88,
            ),
            "TYPO": _tier(
                4,
                core_forms=["jegukan", "cekukan", "cukukan", "jegugan", "segukan"],
                regex=[
                    "aduh\\s*c[uo]+k+[ae]*n+",
                    "duh\\s*c[uo]+k+[ae]*n+",
                    "kok\\s*c[uo]+k+[ae]*n+",
                    "lagi\\s*c[uo]+k+[ae]*n+",
                    "masih\\s*c[uo]+k+[ae]*n+",
                    "\\bcu+k+[uo]+k+[ae]+n+\\b",
                    "(?<!se)se+g+[uo]+k+[ae]*n+\\b",
                    "\\bce+g+[uo]+[ae]*n+\\b",
                    "\\bce+k+[uo]+[ae]*n+\\b",
                    "\\bce+g+[uo]+k+\\s+[ae]*n+\\b",
                    "\\bju+g+[uo]+k+[ae]*n+\\b",
                    "\\bce+k+[uo]+g+[ae]*n+\\b",
                    "\\bce+g+[uo]+g+[ae]*n+\\b",
                    "\\bje+g+[uo]+g+[ae]*n+\\b",
                    "\\bje+k+[uo]+g+[ae]*n+\\b",
                    "\\bc+e*b+u+k+a+n+\\b",
                    "\\bja+g+u+k+[ae]*n+\\b",
                    "\\bc+u+k+[ae]*n+\\b",
                ],
                variants=["auto_typo"],
                context_forms=["aduh *", "duh *", "kok *", "lagi *", "masih *"],
                fuzzy_skip=["cekukan", "cukukan"],
                fuzzy_threshold=0.78,
            ),
            "SILENT": _tier(
                4,
                regex=[
                    "ce+g+[uo]+k+[ae]*n+\\s*(dari\\s*tadi|terus|mulu|melulu|lagi)",
                    "(ga|gak|tidak|nggak)\\s*(ilang|hilang)\\s*[\\w\\s]*ce+g+[uo]+k+[ae]*n*",
                    "ce+g+[uo]+k+[ae]*n+\\s*(ga|gak|nggak)\\s*(ilang|hilang)",
                    "capek\\s*ce+g+[uo]+k+[ae]*n*",
                    "ce+g+[uo]+k+[ae]*n+\\s*ga\\s*ilang",
                ],
            ),
            "CONTEXT": _tier(
                2,
                core_forms=["tersedak", "kesedak", "ceguk"],
                regex=[
                    "te+rs+e+d+[ae]+k+",
                    "ke+s+e+d+[ae]+k+",
                    "(?<![a-zA-Z])ce+g+[uo]+k+(?![a-zA-Z])",
                ],
            ),
            "FP": _tier(
                1,
                core_forms=["nyendawa", "sendawa", "sesegukan"],
                regex=[
                    "ny+e+nd+[ao]+w+[ao]*",
                    "se+nd+[ao]+w+[ao]*",
                    "\\bhi+k+\\b",
                    "\\bse+se+g+[uo]+k+[ae]*n+\\b",
                ],
                neg_context=["ekonomi", "minor", "kecil", "sementara"],
            ),
        },
        "neg_context_global": ["jangan", "bukan", "kayak", "misal", "contoh"],
        "fuzzy_hits_cap": 8,
    },
    # =====================================================================
    # ENGLISH (spec §2.2)
    # =====================================================================
    "en": {
        "script": "latin",
        "tiers": {
            "CORE": _tier(
                5,
                core_forms=["hiccup", "hiccups", "hic", "hiccough"],
                regex=["\\bhiccup+s?\\b", "\\bhiccu+p+s?\\b", "\\*hic\\*", "\\bhic+\\b"],
                variants=["auto_typo"],
                fuzzy_threshold=0.88,
            ),
            "TYPO": _tier(
                4,
                core_forms=["hicup", "hicups", "hickup", "hickups"],
                regex=["\\bhicup+s?\\b", "\\bhickup+s?\\b", "\\bh[ie]ccup+s?\\b", "\\bhic\\s+cup+s?\\b"],
                variants=["auto_typo"],
                fuzzy_skip=["hic"],
                fuzzy_threshold=0.78,
            ),
            "SILENT": _tier(
                4,
                regex=[
                    "hiccup+s?\\s*(won'?t|can'?t|don'?t|not)\\s*(stop|go away)",
                    "(can'?t|won'?t)\\s*(stop|get rid of)\\s*(the\\s*)?hiccup",
                    "hiccup+s?\\s*(for|like)\\s*(an?\\s*)?(hour|minute|while)",
                    "still\\s*(have|got)\\s*(the\\s*)?hiccup",
                ],
            ),
            "CONTEXT": _tier(2, core_forms=["hiccoughs"], regex=["\\bhiccough+s?\\b"]),
            "FP": _tier(
                1,
                regex=[
                    "(economic|minor|small|little|technical|temporary)\\s*hiccup+s?",
                    "hiccup+s?\\s*(in|with|for)\\s*(the|our|my|their)\\s*\\w+",
                ],
                neg_context=["economic", "minor", "small", "little", "technical", "temporary"],
            ),
        },
        "neg_context_global": ["economic", "minor", "technical"],
        "fuzzy_hits_cap": 8,
    },
    # =====================================================================
    # JAPANESE (spec §2.3) — exact + romanized, TANPA phonetic
    # =====================================================================
    "jp": {
        "script": "japanese",
        "tiers": {
            "CORE": _tier(
                5,
                core_forms=["しゃっくり", "シャックリ", "シャッくり", "しゃッくり", "吃逆"],
                regex=["しゃっ\\s*くり", "シャッ\\s*クリ"],
                romanized=["shakkuri"],
            ),
            "TYPO": _tier(
                4,
                core_forms=["しゃくり", "シャクリ", "ひゃっくり", "ヒャックリ", "ヒック", "ひっく"],
                regex=["吃\\s*逆"],
                romanized=["shakuri", "hyakkuri", "hiku"],
            ),
            "SILENT": _tier(
                4,
                regex=[
                    "しゃっくりが止まら",
                    "シャックリが止まら",
                    "しゃっくり.*止まらない",
                    "しゃっくり.*続く",
                    "しゃっくり.*止め",
                ],
            ),
            "CONTEXT": _tier(2),
            "FP": _tier(1, core_forms=["びっくり", "ビックリ"]),
        },
    },
    # =====================================================================
    # KOREAN (spec §2.4)
    # =====================================================================
    "kr": {
        "script": "korean",
        "tiers": {
            "CORE": _tier(
                5,
                core_forms=["딸꾹질", "딸꾹", "딸각", "딸깍", "딸구질", "딸국"],
                romanized=["ttalkkukjil", "ttalkkuk", "ttalgak", "ttalkkak", "ttalgujil", "ttalguk"],
            ),
            "TYPO": _tier(
                4,
                core_forms=["사레", "사레들", "캑캑", "컥컥"],
                regex=["\\[딸꾹\\]", "\\[딸깍\\]"],
                romanized=["sare", "kyayngkyayng", "keokkeok"],
            ),
            "SILENT": _tier(
                4,
                regex=["딸꾹질이 안", "딸꾹질 계속", "딸꾹질 멈추", "멈추질 않", "딸꾹질 때문에"],
            ),
            "CONTEXT": _tier(
                2,
                core_forms=["트림", "거억", "꺼억", "끄억"],
                regex=["\\[트림\\]"],
            ),
            "FP": _tier(1),
        },
    },
    # =====================================================================
    # INDIA — Hindi + Telugu di-merge (spec §2.5, arch §4.4)
    # =====================================================================
    "in": {
        "script": "devanagari",
        "tiers": {
            "CORE": _tier(
                5,
                core_forms=["हिचकी", "hiccup", "hichki"],
                romanized=["hichki"],
            ),
            "TYPO": _tier(
                4,
                core_forms=["इचकी", "हिचकि", "hicup", "hacup", "hichky"],
                romanized=["ichaki", "hichaki", "hichky"],
            ),
            "SILENT": _tier(4),
            "CONTEXT": _tier(2, core_forms=["हिचकियाँ", "हिचकिया", "हिचकीं"]),
            "FP": _tier(1),
        },
        "include_scripts": ["devanagari", "telugu"],
    },
    # =====================================================================
    # THAI (spec §2.6)
    # =====================================================================
    "th": {
        "script": "thai",
        "tiers": {
            "CORE": _tier(
                5,
                core_forms=["สะอึก", "อาการสะอึก"],
                romanized=["sauek"],
            ),
            "TYPO": _tier(4, core_forms=["สอึก", "สะอิก"], romanized=["sauek"]),
            "SILENT": _tier(4),
            "CONTEXT": _tier(2, core_forms=["สำลัก", "เรอ"]),
            "FP": _tier(1),
        },
    },
    # =====================================================================
    # TELUGU (spec §2.7) — internal; di-merge ke `in` saat load.
    # =====================================================================
    "te": {
        "script": "telugu",
        "tiers": {
            "CORE": _tier(
                5,
                core_forms=["ఎక్కిళ్లు", "ఎక్కిళ్ళు", "ఎక్కిలి", "ekkillu", "ekkili"],
                romanized=["ekkillu", "ekkili"],
            ),
            "TYPO": _tier(
                4,
                core_forms=["ఎకిళ్లు", "ఎకిళ్ళు", "ekilu", "ekkilu", "హిచ్కి", "హిచ్‌కి"],
                romanized=["ekilu", "ekkilu", "hichki"],
            ),
            "SILENT": _tier(4),
            "CONTEXT": _tier(2, core_forms=["ఎక్కిళ్లతో", "త్రేనుపు"]),
            "FP": _tier(1),
        },
    },
}
