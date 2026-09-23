"""Ekstraksi token satu pass: token + offset + raw.

Tidak mengcompile regex bahasa, tidak tahu keyword. Dipakai fuzzy layer
(Fase 3); Fase 1 hanya butuh kontrak `.values`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Token", "TokenList", "extract"]

_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Token:
    raw: str
    start: int
    end: int

    @property
    def values(self) -> str:
        return self.raw


@dataclass(frozen=True)
class TokenList:
    tokens: tuple[Token, ...]
    text: str

    @property
    def values(self) -> list[str]:
        return [t.raw for t in self.tokens]

    def __iter__(self):
        return iter(self.tokens)

    def __len__(self) -> int:
        return len(self.tokens)


def extract(text: str) -> TokenList:
    """Tokenize `text` dalam satu pass (satu iterasi finditer)."""
    toks = tuple(
        Token(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text or "")
    )
    return TokenList(tokens=toks, text=text or "")
