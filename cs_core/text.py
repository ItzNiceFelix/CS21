"""Normalisasi teks bersama.

Baseline TIDAK melakukan lowercasing (regex memakai re.IGNORECASE, bukan
lower()); jadi `normalize` hanya strip + NFC. VTT tag `<...>` dibuang.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["strip_vtt_tags", "normalize", "VTT_TAG_RE"]

# Sama dengan _VTT_TAG_RE di engine lama (AE125, P79): hapus semua tag <...>.
VTT_TAG_RE = re.compile(r"<[^>]+>")


def strip_vtt_tags(text: str) -> str:
    """Buang tag HTML/VTT `<...>` (termasuk timestamp inline `[00:01:23.000]`)."""
    return VTT_TAG_RE.sub("", text)


def normalize(seg) -> str:
    """Normalisasi satu segmen/teks.

    - Ambil `seg["text"]` bila segmen dict, else pakai `seg` sebagai str.
    - Buang tag VTT.
    - Strip spasi ujung.
    - NFC (unicode normalization) — baseline tidak melakukannya, tapi ini
      keputusan arsitektur dan tidak mengubah hasil untuk input yang sudah NFC.
    - TANPA lowercasing: baseline case-sensitive di level Python.
    """
    if isinstance(seg, dict):
        text = seg.get("text", "") or ""
    else:
        text = seg or ""
    text = strip_vtt_tags(str(text))
    return unicodedata.normalize("NFC", text.strip())
