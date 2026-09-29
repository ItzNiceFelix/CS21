"""Kontrak error & exit code cs_core — satu sumber untuk CLI, menu, dan engine.

Exit code (dipakai semua entry point `cs21`):

===  ==========================================================
0    sukses
1    gagal runtime (video/channel tidak ada, 0 hasil, engine error)
2    salah pakai (argumen/flag/nilai tidak valid)
3    jaringan / rate limit / blokir YouTube
4    dependensi hilang (yt-dlp, youtube-transcript-api, cookies)
130  dihentikan user (Ctrl+C)
===  ==========================================================

Pesan untuk user SELALU bahasa Indonesia, satu baris, dan (kalau ada)
disertai satu saran aksi konkret. Detail teknis mentah hanya masuk
`hint` dan dicetak di level `-v/--verbose`.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = [
    "ExitCode",
    "CsError",
    "UsageError",
    "DependencyError",
    "NetworkError",
    "TranscriptUnavailable",
    "describe_transcript_error",
    "first_line",
    "VALID_LANGS",
    "resolve_lang",
]

# Bahasa yang dikenal engine utama (spec transcript + keyword).
VALID_LANGS: dict[str, str] = {
    "id": "Indonesia",
    "en": "English",
    "jp": "Jepang",
    "kr": "Korea",
    "in": "Hindi/India",
    "th": "Thailand",
}

# Alias kode ISO yang sering dipakai orang -> kode internal engine.
_LANG_ALIASES: dict[str, str] = {
    "ja": "jp", "jpn": "jp", "japanese": "jp",
    "ko": "kr", "kor": "kr", "korean": "kr",
    "hi": "in", "hin": "in", "te": "in", "telugu": "in", "india": "in",
    "thai": "th",
    "ind": "id", "indonesian": "id",
    "eng": "en", "english": "en",
    "id-id": "id", "en-us": "en", "en-gb": "en", "ja-jp": "jp", "ko-kr": "kr",
}

class ExitCode(IntEnum):
    OK = 0
    FAIL = 1
    USAGE = 2
    NETWORK = 3
    DEPENDENCY = 4
    INTERRUPTED = 130

class CsError(Exception):
    """Error yang sudah ramah-user: pesan + saran + exit code."""

    code: ExitCode = ExitCode.FAIL

    def __init__(self, message: str, *, hint: str = "", code: ExitCode | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        if code is not None:
            self.code = code

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message

class UsageError(CsError):
    """Argumen/nilai tidak valid (exit 2)."""

    code = ExitCode.USAGE

class DependencyError(CsError):
    """Ada paket/binary/file wajib yang belum siap (exit 4)."""

    code = ExitCode.DEPENDENCY

class NetworkError(CsError):
    """Jaringan, rate limit, atau blokir YouTube (exit 3)."""

    code = ExitCode.NETWORK

class TranscriptUnavailable(CsError):
    """Transkrip tidak bisa diambil, tapi bukan salah user (exit 1)."""

    code = ExitCode.FAIL

def first_line(text: str) -> str:
    """Baris bermakna pertama dari pesan library (sering diawali '\\n')."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""

def resolve_lang(code: str) -> str:
    """Normalisasi kode bahasa; `UsageError` bila tak dikenal.

    Menerima `id/en/jp/kr/in/th` plus alias (`ja`, `ko`, `hi`, `te`, `id-ID`, ...).
    """
    raw = (code or "").strip().lower()
    if not raw:
        return "id"
    if raw in VALID_LANGS:
        return raw
    alias = _LANG_ALIASES.get(raw)
    if alias:
        return alias
    valid = ", ".join(VALID_LANGS)
    raise UsageError(
        f"bahasa '{code}' tidak dikenal",
        hint=f"pilih salah satu: {valid}",
    )

# Alasan transkrip gagal -> (pesan Indonesia, saran aksi).
# Dicocokkan lewat NAMA KELAS exception (stabil antar versi library) supaya
# `cs_core` tidak perlu mengimpor youtube-transcript-api di jalur ringan.
_TRANSCRIPT_REASONS: dict[str, tuple[str, str]] = {
    "VideoUnavailable": ("video tidak tersedia (dihapus/privat)", "cek ID-nya, atau coba video lain"),
    "InvalidVideoId": ("ID video tidak valid", "pakai 11 karakter ID, bukan URL lengkap"),
    "TranscriptsDisabled": ("transkrip dinonaktifkan pemilik channel", "coba menu Index/Age (jalur yt-dlp) atau video lain"),
    "NoTranscriptFound": ("tidak ada transkrip untuk bahasa ini", "coba bahasa lain: --lang en"),
    "AgeRestricted": ("video dibatasi umur (age-restricted)", "pakai menu Recovery Age + setup cookies"),
    "PoTokenRequired": ("YouTube minta token tambahan (PoToken)", "perbarui cookies: bash setup_cookies.sh"),
    "IpBlocked": ("IP kamu diblokir sementara oleh YouTube", "tunggu 15-60 menit, lalu pakai cookies"),
    "RequestBlocked": ("permintaan diblokir YouTube (rate limit)", "tunggu 15-60 menit, lalu pakai cookies"),
    "YouTubeRequestFailed": ("permintaan ke YouTube gagal", "cek koneksi internet"),
    "YouTubeDataUnparsable": ("respons YouTube tidak bisa dibaca", "perbarui: pip install -U youtube-transcript-api"),
    "VideoUnplayable": ("video tidak bisa diputar", "coba video lain"),
    "CookieError": ("cookies bermasalah", "jalankan: bash setup_cookies.sh"),
    "CookieInvalid": ("cookies tidak valid", "jalankan: bash setup_cookies.sh"),
    "CookiePathInvalid": ("file cookies tidak ditemukan", "jalankan: bash setup_cookies.sh"),
    "Timeout": ("permintaan ke YouTube timeout", "cek koneksi lalu ulangi"),
    "ConnectionError": ("tidak bisa menyambung ke YouTube", "cek koneksi internet"),
}

def describe_transcript_error(exc: BaseException, video_id: str = "", lang: str = "") -> CsError:
    """Terjemahkan exception transcript apa pun -> `CsError` satu baris.

    Menelusuri `__cause__`/`__context__` supaya pesan asli library tetap
    terdeteksi walau sudah dibungkus `TranscriptError`.
    """
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        name = type(node).__name__
        reason = _TRANSCRIPT_REASONS.get(name)
        if reason:
            pesan, saran = reason
            label = f" ({video_id})" if video_id else ""
            return TranscriptUnavailable(f"transkrip gagal{label}: {pesan}", hint=saran)
        node = node.__cause__ or node.__context__

    detail = first_line(str(exc)) or type(exc).__name__
    label = f" ({video_id})" if video_id else ""
    return TranscriptUnavailable(
        f"transkrip gagal{label}: {detail}",
        hint="jalankan `cs21 doctor` untuk cek dependensi & cookies",
    )
