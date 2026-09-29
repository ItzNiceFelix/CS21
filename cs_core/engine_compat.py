"""Helper bersama untuk engine lama (`cs20_*.py`).

Engine lama tidak boleh mengimpor `cs_core.errors` secara langsung: kalau
`cs_core` tidak ada (mis. skrip disalin sendirian), engine harus tetap jalan.
Modul ini menyembunyikan detail itu di satu tempat.
"""

from __future__ import annotations

__all__ = ["normalize_channel", "resolve_lang_arg", "normalize_lang"]


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
    text = text.split("/", 1)[0]  # buang /videos, /streams, /shorts, ...
    return text.lstrip("@").rstrip("/")


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
