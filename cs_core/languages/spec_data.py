"""Data tier keyword — PORT APA ADANYA dari `_ALL_KEYWORD_TIERS`
(cs20_engine.py), dikurangi `(?!)` (P4: tier kosong jadi list kosong).

Fase 2 akan menggantinya dengan deklarasi `core_forms` + generator varian.
"""

__all__ = ['KEYWORD_TIERS', 'TRANSCRIPT_LANGS']

# Merged per-tier di load('in'); te tetap tersedia internal.
KEYWORD_TIERS = {
    'id': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                'ce+g+[uo]+k+[ae]+n+',
                'ce+g+[uo]+k+[ae]+n+nya',
                'ce+g+[uo]+k+[ae]+n+ku',
                'ce+c+e+g+[uo]+k+[ae]+n+',
                'ce+k+[uo]+k+[ae]+n+',
                'ce+k+[uo]+k+[ae]+n+nya',
                'ce+k+[uo]+k+[ae]+n+ku',
                'je+g+[uo]+k+[ae]+n+',
                'ke+je+g+[uo]+k+[ae]+n+',
                'ke+ce+g+[uo]+k+[ae]+n*',
                'ce+g+[uo]+k+e+n+',
                'ce+k+[uo]+k+e+n+',
                '\\*hi+k+\\*',
                '\\*hi+c+\\*',
                '\\*ngi+k+\\*',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                'aduh\\s*c[uo]+k+[ae]*n+',
                'duh\\s*c[uo]+k+[ae]*n+',
                'kok\\s*c[uo]+k+[ae]*n+',
                'lagi\\s*c[uo]+k+[ae]*n+',
                'masih\\s*c[uo]+k+[ae]*n+',
                '\\bcu+k+[uo]+k+[ae]+n+\\b',
                '(?<!se)se+g+[uo]+k+[ae]*n+\\b',
                '\\bce+g+[uo]+[ae]*n+\\b',
                '\\bce+k+[uo]+[ae]*n+\\b',
                '\\bce+g+[uo]+k+\\s+[ae]*n+\\b',
                '\\bju+g+[uo]+k+[ae]*n+\\b',
                '\\bce+k+[uo]+g+[ae]*n+\\b',
                '\\bce+g+[uo]+g+[ae]*n+\\b',
                '\\bje+g+[uo]+g+[ae]*n+\\b',
                '\\bje+k+[uo]+g+[ae]*n+\\b',
                '\\bc+e*b+u+k+a+n+\\b',
                '\\bja+g+u+k+[ae]*n+\\b',
                '\\bc+u+k+[ae]*n+\\b',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [
                'ce+g+[uo]+k+[ae]*n+\\s*(dari\\s*tadi|terus|mulu|melulu|lagi)',
                '(ga|gak|tidak|nggak)\\s*(ilang|hilang)\\s*[\\w\\s]*ce+g+[uo]+k+[ae]*n*',
                'ce+g+[uo]+k+[ae]*n+\\s*(ga|gak|nggak)\\s*(ilang|hilang)',
                'capek\\s*ce+g+[uo]+k+[ae]*n*',
                'ce+g+[uo]+k+[ae]*n+\\s*ga\\s*ilang',
            ],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [
                'te+rs+e+d+[ae]+k+',
                'ke+s+e+d+[ae]+k+',
                '(?<![a-zA-Z])ce+g+[uo]+k+(?![a-zA-Z])',
            ],
        },
        'FP': {
            'bobot': 1,
            'patterns': [
                'ny+e+nd+[ao]+w+[ao]*',
                'se+nd+[ao]+w+[ao]*',
                '\\bhi+k+\\b',
                '\\bse+se+g+[uo]+k+[ae]*n+\\b',
            ],
        },
    },
    'en': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                '\\bhiccup+s?\\b',
                '\\bhiccu+p+s?\\b',
                '\\*hic\\*',
                '\\bhic+\\b',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                '\\bhicup+s?\\b',
                '\\bhickup+s?\\b',
                '\\bh[ie]ccup+s?\\b',
                '\\bhic\\s+cup+s?\\b',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [
                'hiccup+s?\\s*(won\'?t|can\'?t|don\'?t|not)\\s*(stop|go away)',
                '(can\'?t|won\'?t)\\s*(stop|get rid of)\\s*(the\\s*)?hiccup',
                'hiccup+s?\\s*(for|like)\\s*(an?\\s*)?(hour|minute|while)',
                'still\\s*(have|got)\\s*(the\\s*)?hiccup',
            ],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [
                '\\bhiccough+s?\\b',
            ],
        },
        'FP': {
            'bobot': 1,
            'patterns': [
                '(economic|minor|small|little|technical|temporary)\\s*hiccup+s?',
                'hiccup+s?\\s*(in|with|for)\\s*(the|our|my|their)\\s*\\w+',
            ],
        },
    },
    'jp': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                'しゃっくり',
                'シャックリ',
                'シャッくり',
                'しゃッくり',
                '吃逆',
                'しゃっ\\s*くり',
                'シャッ\\s*クリ',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                'しゃくり',
                'シャクリ',
                'ひゃっくり',
                'ヒャックリ',
                'ヒック',
                'ひっく',
                '吃\\s*逆',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [
                'しゃっくりが止まら',
                'シャックリが止まら',
                'しゃっくり.*止まらない',
                'しゃっくり.*続く',
                'しゃっくり.*止め',
            ],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [],
        },
        'FP': {
            'bobot': 1,
            'patterns': [
                'びっくり',
                'ビックリ',
            ],
        },
    },
    'kr': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                '딸꾹질',
                '딸꾹',
                '딸각',
                '딸깍',
                '딸구질',
                '딸국',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                '\\[딸꾹\\]',
                '\\[딸깍\\]',
                '사레',
                '사레들',
                '캑캑',
                '컥컥',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [
                '딸꾹질이 안',
                '딸꾹질 계속',
                '딸꾹질 멈추',
                '멈추질 않',
                '딸꾹질 때문에',
            ],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [
                '트림',
                '거억',
                '꺼억',
                '끄억',
                '\\[트림\\]',
            ],
        },
        'FP': {
            'bobot': 1,
            'patterns': [],
        },
    },
    'in': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                'हिचकी',
                '\\bhiccup\\b',
                '\\bhichki\\b',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                'इचकी',
                'हिचकि',
                '\\bhicup\\b',
                '\\bh[ae]cup\\b',
                '\\bhichky\\b',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [
                'हिचकियाँ',
                'हिचकिया',
                'हिचकीं',
            ],
        },
        'FP': {
            'bobot': 1,
            'patterns': [],
        },
    },
    'th': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                'สะอึก',
                'อาการสะอึก',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                'สอึก',
                'สะอิก',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [
                'สำลัก',
                'เรอ',
            ],
        },
        'FP': {
            'bobot': 1,
            'patterns': [],
        },
    },
    'te': {
        'CORE': {
            'bobot': 5,
            'patterns': [
                'ఎక్కిళ్లు',
                'ఎక్కిళ్ళు',
                'ఎక్కిలి',
                '\\bekkillu\\b',
                '\\bekkili\\b',
            ],
        },
        'TYPO': {
            'bobot': 4,
            'patterns': [
                'ఎకిళ్లు',
                'ఎకిళ్ళు',
                '\\bekilu\\b',
                '\\bekkilu\\b',
                'హిచ్కి',
                'హిచ్‌కి',
            ],
        },
        'SILENT': {
            'bobot': 4,
            'patterns': [],
        },
        'CONTEXT': {
            'bobot': 2,
            'patterns': [
                'ఎక్కిళ్లతో',
                'త్రేనుపు',
            ],
        },
        'FP': {
            'bobot': 1,
            'patterns': [],
        },
    },
}

# P9: te dipetakan eksplisit; default untuk lang tak dikenal.
TRANSCRIPT_LANGS = {
    'id': ['id', 'en', 'id-ID'],
    'en': ['en', 'en-US', 'en-GB'],
    'jp': ['ja', 'ja-JP'],
    'kr': ['ko', 'ko-KR'],
    'in': ['hi', 'hi-IN', 'te', 'te-IN'],
    'th': ['th', 'th-TH'],
    'te': ['te', 'te-IN', 'hi'],
}

DEFAULT_TRANSCRIPT_LANGS = ['id', 'en', 'id-ID']
