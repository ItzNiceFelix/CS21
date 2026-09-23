"""Transcript fetcher + adapter normalisasi (Fase 4).

- `parse_vtt_text` / `parse_vtt_file`: VTT -> `[{sec, text}]`, collapse by
  timestamp ambil teks terpanjang (baseline `parse_vtt_content`), strip `<...>`.
  `parse_vtt_file` streaming per baris (tidak load penuh).
- `fetch_api`: youtube-transcript-api (lazy import), port urutan
  cookies -> UA rotation -> fallback dari `cs20_engine._fetch_transcript`.
- `fetch_vtt`: yt-dlp (lazy import) -> VTT -> parse.
- `get_segments`: cache-first (lihat `cs_core.cache`).
- P6: semua sumber dinormalkan ke `{sec, text}` (adapter `start` -> `sec`).

`TRANSCRIPT_LANGS` di-re-export dari `cs_core.languages.spec_data` (P9:
`te -> [te, te-IN, hi]`), bukan diduplikasi.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from . import cache as _cache
from .languages import spec_data as _spec_data

__all__ = [
    "TRANSCRIPT_LANGS",
    "DEFAULT_TRANSCRIPT_LANGS",
    "transcript_langs",
    "parse_vtt_text",
    "parse_vtt_file",
    "fetch_api",
    "fetch_vtt",
    "get_segments",
]

# Re-export peta bahasa (satu sumber kebenaran: spec_data).
TRANSCRIPT_LANGS = _spec_data.TRANSCRIPT_LANGS
DEFAULT_TRANSCRIPT_LANGS = _spec_data.DEFAULT_TRANSCRIPT_LANGS

# Baselines VTT (P79, P112; AE125, AE146).
_VTT_CUE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")

# Port dari `transcript.py` engine lama (`sub_langs` yt-dlp index mode).
_LANG_SUB_MAP = {
    "id": ["id", "en"],
    "en": ["en", "en-US", "en-GB"],
    "jp": ["ja", "ja-JP"],
    "kr": ["ko", "ko-KR"],
    "in": ["hi", "hi-IN", "en"],
}

_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; POCO X4 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Samsung Galaxy S23) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
_ua_index = 0


def transcript_langs(lang: str) -> list:
    """Daftar kode transcript untuk `lang` (default ID seperti baseline)."""
    return list(TRANSCRIPT_LANGS.get(lang, DEFAULT_TRANSCRIPT_LANGS))


class TranscriptError(RuntimeError):
    """Semua jalur fetch gagal; caller yang memutuskan statusnya."""


# ---------------------------------------------------------------------------
# VTT parse
# ---------------------------------------------------------------------------
def _vtt_time_to_sec(vtt_time: str) -> int:
    """`00:01:23.456` -> 83 (int detik, tanpa pembulatan).

    Port dari `parse_vtt_content`/`_parse_vtt` (parser memakai `match` pada
    `_VTT_TIMESTAMP_RE` yang mengabaikan prefiks; di sini split manual).
    """
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})", vtt_time.strip())
    if not m:
        return 0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def parse_vtt_text(text: str) -> list:
    """Parse VTT string -> `[{sec, text}]`.

    Collapse by timestamp start, ambil teks terpanjang. Strip tag `<...>`.
    Hasil sort by `sec`.

    Delegasi ke parser berbasis-baris (`_parse_vtt_lines`) supaya file & string
    memakai SATU implementasi. Catatan: parser lama gagal bila ada cue baru
    tanpa baris kosong pemisah (VTT YouTube selalu punya pemisah, tapi VTT
    buatan/aneh bisa tidak) — versi ini menanganinya dengan benar.
    """
    return _parse_vtt_lines(text.splitlines())


def parse_vtt_file(path) -> list:
    """Parse file VTT dengan iterasi baris (tidak load penuh ke memori)."""
    return _parse_vtt_lines(_iter_lines(path))


def _iter_lines(path):
    """Generator baris file VTT; tidak menyimpan seluruh file."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            yield line


def _parse_vtt_lines(lines) -> list:
    """Parser VTT berbasis iterator baris (versi streaming `parse_vtt_text`)."""
    segments: dict = {}
    pending = None  # (start_sec, [parts]) sedang dikumpulkan

    def _flush():
        if pending is None:
            return
        start_sec, parts = pending
        combined = " ".join(parts).strip()
        if combined and len(combined) > len(segments.get(start_sec, "")):
            segments[start_sec] = combined

    for raw_line in lines:
        line = raw_line.strip()
        cue = _VTT_CUE_RE.match(line)
        if cue:
            _flush()
            pending = (_vtt_time_to_sec(cue.group(1)), [])
            continue
        if pending is not None:
            if not line:
                _flush()
                pending = None
            else:
                clean = _VTT_TAG_RE.sub("", line).strip()
                if clean:
                    pending[1].append(clean)
    _flush()
    return [{"sec": s, "text": t} for s, t in sorted(segments.items())]


# ---------------------------------------------------------------------------
# Normalisasi segmen (P6)
# ---------------------------------------------------------------------------
def _normalize_segments(raw) -> list:
    """Normalisasi segmen ke `[{sec, text}]`.

    Dukung `{start, duration}` (yt-api) dan `{sec}` (VTT/index).
    """
    out = []
    for seg in raw or []:
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if "sec" in seg:
            sec = seg.get("sec", 0)
        else:
            sec = int(seg.get("start", 0) or 0)
        out.append({"sec": sec, "text": text})
    return out


# ---------------------------------------------------------------------------
# Fetch: youtube-transcript-api
# ---------------------------------------------------------------------------
def _next_user_agent() -> str:
    global _ua_index
    ua = _USER_AGENTS[_ua_index % len(_USER_AGENTS)]
    _ua_index += 1
    return ua


def _build_session_with_cookies(cookies_path: str):
    """Port `_build_session_with_cookies` (load Netscape cookie jar)."""
    import http.cookiejar
    import time

    import requests  # lazy: hanya jalur fetch

    session = requests.Session()
    session.headers.update({"User-Agent": _next_user_agent()})
    try:
        jar = http.cookiejar.MozillaCookieJar(cookies_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        now = int(time.time())
        for ck in jar:
            if ck.expires and ck.expires < now:
                continue
            session.cookies.set(ck.name, ck.value, domain=ck.domain, path=ck.path)
    except Exception:
        pass  # gagal load cookie: session tetap jalan tanpa cookies
    return session


def fetch_api(video_id: str, lang: str = "id") -> tuple:
    """Fetch transkrip via youtube-transcript-api. Return `(segments, "yt-api")`.

    Port urutan: cookies -> UA rotation -> fallback polos. Exception
    `TranscriptError` bila semua gagal (caller yang urus).
    """
    from youtube_transcript_api import (  # lazy
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApi,
    )

    langs = transcript_langs(lang)
    cookies_path = os.environ.get("CS_COOKIES", "").strip()

    def _raw(result):
        return result.to_raw_data() if hasattr(result, "to_raw_data") else list(result)

    # 1) Dengan cookies
    if cookies_path and os.path.exists(cookies_path):
        try:
            session = _build_session_with_cookies(cookies_path)
            api = YouTubeTranscriptApi(http_client=session)
            result = api.fetch(video_id, languages=langs)
            return _normalize_segments(_raw(result)), "yt-api"
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as exc:
            raise TranscriptError(str(exc)) from exc
        except Exception:
            pass  # fallback ke bawah

    # 2) Tanpa cookies: rotasi User-Agent
    try:
        import requests  # lazy

        session = requests.Session()
        session.headers.update({"User-Agent": _next_user_agent()})
        api = YouTubeTranscriptApi(http_client=session)
        result = api.fetch(video_id, languages=langs)
        return _normalize_segments(_raw(result)), "yt-api"
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as exc:
        raise TranscriptError(str(exc)) from exc
    except Exception:
        pass

    # 3) Fallback paling dasar
    api = YouTubeTranscriptApi()
    result = api.fetch(video_id, languages=langs)
    return _normalize_segments(_raw(result)), "yt-api"


# ---------------------------------------------------------------------------
# Fetch: yt-dlp -> VTT
# ---------------------------------------------------------------------------
def fetch_vtt(video_id: str, lang: str = "id", *, cookies=None, output_dir=None):
    """Download auto-subs via yt-dlp, parse VTT. Return `(segments, "ytdlp-vtt")`.

    `cookies` = path cookies.txt opsional; `output_dir` opsional (default
    tmpdir, dibersihkan sendiri).
    """
    sub_langs = _LANG_SUB_MAP.get(lang, ["id", "en"])
    url = f"https://www.youtube.com/watch?v={video_id}"
    own_dir = output_dir is None
    out_dir = output_dir or tempfile.mkdtemp(prefix="cs20_vtt_")
    os.makedirs(out_dir, exist_ok=True)
    outtmpl = os.path.join(out_dir, f"{video_id}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--write-auto-subs",
        "--sub-langs", ",".join(sub_langs),
        "--sub-format", "vtt",
        "--skip-download",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--socket-timeout", "20",
        "-o", outtmpl,
        url,
    ]
    if cookies:
        cmd[1:1] = ["--cookies", str(cookies)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise TranscriptError("yt-dlp not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscriptError("yt-dlp timeout") from exc
    except Exception as exc:
        raise TranscriptError(f"{type(exc).__name__}: {exc}") from exc

    vtt_files = sorted(
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith(f"{video_id}.") and f.endswith(".vtt")
    )
    if not vtt_files:
        err = ((proc.stdout or "") + " " + (proc.stderr or "")).strip()
        if own_dir:
            _cleanup(out_dir)
        raise TranscriptError(
            f"yt-dlp no VTT produced (exit {proc.returncode}): {err[:200]}"
        )

    segments = parse_vtt_file(vtt_files[0])
    if own_dir:
        _cleanup(out_dir)
    if not segments:
        raise TranscriptError("VTT parsed to 0 segments")
    return segments, "ytdlp-vtt"


def _cleanup(path: str) -> None:
    try:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cache-first orchestrator
# ---------------------------------------------------------------------------
def get_segments(
    video_id: str,
    lang: str = "id",
    *,
    source_hint: str = "auto",
    use_cache: bool = True,
    force_refresh: bool = False,
    root=None,
) -> tuple:
    """Ambil segmen `(segments, source, cache_status)`.

    cache_status ∈ `"hit" | "miss" | "disabled"`.
    Alur: cache-first (hit -> return); miss -> fetch -> write -> return.
    """
    if use_cache and not force_refresh:
        cached = _cache.read(video_id, lang, root=root)
        if cached is not None:
            return cached, _read_source(video_id, lang, root), "hit"

    status = "miss" if use_cache else "disabled"

    if source_hint == "ytdlp-vtt":
        segments, source = fetch_vtt(video_id, lang)
    else:
        segments, source = fetch_api(video_id, lang)

    if use_cache:
        try:
            _cache.write(video_id, lang, segments, source=source, root=root)
        except Exception:
            pass  # kegagalan cache tidak boleh menjatuhkan hasil fetch
    return segments, source, status


def _read_source(video_id: str, lang: str, root) -> str:
    meta = _cache.read_meta(_cache.cache_path(video_id, lang, root))
    return (meta or {}).get("source", "cache")
