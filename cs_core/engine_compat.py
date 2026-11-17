"""Helper bersama untuk engine lama (`cs20_*.py`).

Engine lama tidak boleh mengimpor `cs_core.errors` secara langsung: kalau
`cs_core` tidak ada (mis. skrip disalin sendirian), engine harus tetap jalan.
Modul ini menyembunyikan detail itu di satu tempat.
"""

from __future__ import annotations

import re

__all__ = [
    "normalize_channel",
    "channel_base_url",
    "is_raw_channel_id",
    "resolve_lang_arg",
    "normalize_lang",
    "normalize_content_type",
    "CONTENT_TYPES",
    "DEFAULT_CONTENT_TYPE",
    "MIN_VIDEO_SECONDS",
    "MATCH_FILTER_VIDEO",
]

# Tipe konten scan yang dikenal engine.
CONTENT_TYPES = ("all", "video", "live")
DEFAULT_CONTENT_TYPE = "all"

# Ambang video pendek. Requirement: video <60 detik dibuang, 60 detik termasuk.
MIN_VIDEO_SECONDS = 60
MATCH_FILTER_VIDEO = f"duration>={MIN_VIDEO_SECONDS}"

def normalize_content_type(raw: str, default: str = DEFAULT_CONTENT_TYPE) -> str:
    """Kode tipe konten internal; nilai tak dikenal -> `default`.

    Tidak melempar: engine lama tetap jalan walau argumennya kotor. Validasi
    yang menampilkan error ke user ada di CLI/menu.
    """
    code = (raw or "").strip().lower()
    return code if code in CONTENT_TYPES else default


def normalize_channel(raw: str) -> str:
    """Bersihkan input channel: URL, '@', spasi, prefix `channel/` / `c/`."""
    text = (raw or "").strip().replace(" ", "")
    for prefix in (
        "https://www.youtube.com/",
        "http://www.youtube.com/",
        "https://youtube.com/",
        "http://youtube.com/",
        "www.youtube.com/",
        "youtube.com/",
    ):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.split("?", 1)[0].split("#", 1)[0]
    if text.startswith("channel/"):
        text = text[len("channel/"):]
    elif text.startswith("c/"):
        text = text[2:]
    elif text.startswith("user/"):
        text = text[len("user/"):]
    text = text.split("/", 1)[0]  # buang /videos, /streams, /shorts, ...
    return text.lstrip("@").rstrip("/")

_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")

def is_raw_channel_id(value: str) -> bool:
    """True untuk channel_id mentah YouTube (`UC` + 22 karakter)."""
    return bool(_CHANNEL_ID_RE.fullmatch((value or "").strip()))

def channel_base_url(raw: str) -> str:
    """Base URL kanal yang benar untuk handle, URL, atau channel_id.

    Kanal besar kadang tidak bisa diakses lewat handle karena tabrakan vanity
    URL (mis. `@aerithlive` di-redirect YouTube ke `/Aerith`). Format
    `/channel/UCxxx` selalu menunjuk kanal yang benar, jadi ID mentah dan URL
    `/channel/...` dipertahankan.
    """
    channel = normalize_channel(raw)
    if not channel:
        return ""
    if is_raw_channel_id(channel):
        return f"https://www.youtube.com/channel/{channel}"
    return f"https://www.youtube.com/@{channel}"


def normalize_lang(code: str, default: str = "id") -> str:
    """Kode bahasa internal; tak dikenal -> `default` (tanpa melempar)."""
    raw = (code or "").strip().lower()
    if not raw:
        return default
    try:
        from .errors import VALID_LANGS, _LANG_ALIASES  # type: ignore[attr-defined]

        if raw in VALID_LANGS:
            return raw
        alias = _LANG_ALIASES.get(raw)
        if alias:
            return alias
    except Exception:
        if raw in ("id", "en", "jp", "kr", "in", "th"):
            return raw
    return default


def resolve_lang_arg(code: str, default: str = "id") -> str:
    """Alias `normalize_lang` dengan nama eksplisit untuk argumen CLI."""
    return normalize_lang(code, default=default)
