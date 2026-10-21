"""Normalisasi input video YouTube -> ID 11 karakter.

Satu tempat untuk CLI dan menu: user boleh menempel URL apa pun yang umum
(`youtu.be`, `watch?v=`, `/shorts/`, `/embed/`, `/live/`) atau ID mentah.
Sebelumnya hanya menu yang menormalkan; CLI langsung menyerahkan string apa
adanya ke library sehingga URL utuh jadi `InvalidVideoId`.
"""

from __future__ import annotations

import re

__all__ = ["VIDEO_ID_RE", "parse_video_id", "video_url", "is_video_id"]

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Path YouTube yang diikuti ID langsung: /shorts/ID, /embed/ID, /live/ID, /v/ID.
_PATH_ID_RE = re.compile(
    r"/(?:shorts|embed|live|v|e)/([A-Za-z0-9_-]{11})(?:[?&#/]|$)"
)
_QUERY_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})(?:[&#]|$)")
_BARE_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")

def is_video_id(text: str) -> bool:
    return bool(VIDEO_ID_RE.match(text or ""))

def parse_video_id(raw: str) -> str:
    """Ambil ID 11 karakter dari URL/ID; `""` bila tidak ada.

    Menerima: ID mentah, `youtu.be/ID`, `watch?v=ID`, `/shorts/ID`,
    `/embed/ID`, `/live/ID`, dengan atau tanpa skema, plus query/hash apa pun.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if is_video_id(text):
        return text

    match = _QUERY_ID_RE.search(text) or _PATH_ID_RE.search(text)
    if match:
        return match.group(1)

    # Fallback terakhir: potongan 11 karakter yang berdiri sendiri di URL
    # (mis. `youtube.com/ID` tanpa prefix apa pun).
    if "/" in text or "?" in text:
        match = _BARE_ID_RE.search(text)
        if match:
            return match.group(1)
    return ""

def video_url(video_id: str, sec: float | int | None = None) -> str:
    """URL tonton; `sec` menambahkan `?t=` supaya langsung lompat ke momen."""
    url = f"https://youtu.be/{video_id}"
    if sec is not None and float(sec) > 0:
        return f"{url}?t={int(sec)}"
    return url
