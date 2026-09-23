#!/usr/bin/env python3
"""Fase 0 — perekam baseline 4 engine.

Jalankan di Termux (punya yt-dlp / youtube-transcript-api / rich) untuk merekam
input segmen mentah + output tiap engine ke satu file JSON. Skrip ini TIDAK
menyentuh kode engine; hanya mengimpor fungsi publik/privatnya.

Semua dependency berat (rich, youtube-transcript-api, requests) di-import lazy di
dalam fungsi supaya `--help` dan `--dry-run` tetap jalan di mesin tanpa deps itu
(mis. PC Windows dev).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Engine lama mencetak emoji ke stdout; di console non-UTF8 (Windows dev) itu
# meledak. Paksa UTF-8 bila bisa, supaya import engine tetap jalan.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Baseline perilaku: Fase 5+ baru mengaktifkan float/video_duration.
# Fase 0 merekam penanda literal "baseline" (sesuai kontrak plan §2 & §4).
BASELINE_DEDUP_MODE = "baseline"
BASELINE_CLUSTER_MODE = "baseline"

ALL_ENGINES = ("e", "ie", "ae", "cs")

_LANG_SUB_MAP = {
    "id": ["id", "en"],
    "en": ["en", "en-US", "en-GB"],
    "jp": ["ja", "ja-JP"],
    "kr": ["ko", "ko-KR"],
    "in": ["hi", "hi-IN", "te", "te-IN", "en"],
    "th": ["th", "th-TH"],
}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ==============================================================================
# FETCH VIDEO IDS — yt-dlp flat-playlist (di-skip rapi bila yt-dlp absen)
# ==============================================================================
def _ytdlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def fetch_video_ids(channel: str, limit: int) -> list[str]:
    """Ambil ID via yt-dlp flat-playlist.

    Return [] bila yt-dlp tak tersedia / gagal. Never raises.
    """
    if not _ytdlp_available():
        _log("[!] yt-dlp tidak ditemukan — daftar video ID kosong.")
        return []

    unlimited = limit <= 0
    base = channel.strip()
    if not (base.startswith("http://") or base.startswith("https://")):
        # channel_id mentah (UCxxxx...) BUKAN format @handle — pakai /channel/.
        if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", base):
            base = f"https://www.youtube.com/channel/{base}"
        else:
            base = f"https://www.youtube.com/@{base.removeprefix('@')}"
    base = base.rstrip("/")
    if "/videos" not in base and "/streams" not in base:
        base = f"{base}/videos"

    cmd = ["yt-dlp", "--flat-playlist", "--print", "id"]
    if not unlimited:
        cmd += ["--playlist-end", str(limit)]
    cmd += ["--quiet", "--no-warnings", base]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180 if unlimited else 60
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log(f"[!] yt-dlp gagal: {exc}")
        return []

    ids: list[str] = []
    for line in result.stdout.splitlines():
        vid = line.strip()
        if vid and vid not in ids:
            ids.append(vid)
    return ids if unlimited else ids[:limit]


# ==============================================================================
# INPUT SEGMEN MENTAH — satu fetch dipakai ulang oleh engine
# ==============================================================================
def fetch_raw_segments(video_id: str, lang: str) -> tuple[list, str]:
    """Fetch transkrip mentah. Return (segments, source).

    source = "yt-api" (list dict {text,start,duration}) atau "none" bila gagal.
    Dependency di-import lazy.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as exc:  # ImportError / apa pun dari lib
        _log(f"[!] youtube-transcript-api absen: {exc}")
        return [], "none"

    langs = _LANG_SUB_MAP.get(lang, ["id", "en", "id-ID"])
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=langs)
        raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
        return list(raw), "yt-api"
    except Exception as exc:  # noqa: BLE001 — boundary fetch
        _log(f"[!] fetch {video_id} gagal: {type(exc).__name__}: {exc}")
        return [], "none"


# ==============================================================================
# ADAPTER PRIVAT ENGINE — import lazy, semua di satu tempat
# ==============================================================================
def _run_e(video_id: str, channel: str) -> dict:
    """E = cs20_engine.analyze_video (fetch transkrip sendiri + scoring)."""
    import cs20_engine

    cs20_engine._init_lang(_current_lang())
    return cs20_engine.analyze_video(video_id, channel)


def _run_ie(video_id: str, channel: str, segments: list) -> dict | None:
    """IE = scoring murni dari cs20_index_engine._analyze_from_segments.

    Butuh segments gaya index ({sec,text}); bila hanya ada segmen yt-api
    ({start,...}) segmen dikonversi. Return None bila tak bisa jalan.
    """
    if not segments:
        return None
    index_segments = _to_index_segments(segments)
    if not index_segments:
        return None
    import cs20_engine
    from cs20_index_engine import _analyze_from_segments

    cs20_engine._init_lang(_current_lang())
    return _analyze_from_segments(
        video_id,
        channel,
        index_segments,
        cs20_engine.COMPILED_TIERS,
        cs20_engine.ALL_PATTERNS_COMBINED,
    )


def _run_ae(video_id: str, channel: str, segments: list) -> dict | None:
    """AE = cs20_age_engine._analyze_segments (segmen {sec,text})."""
    if not segments:
        return None
    index_segments = _to_index_segments(segments)
    if not index_segments:
        return None
    from cs20_age_engine import _analyze_segments, _load_fuzzy_engine

    compiled, combined, _ok = _load_fuzzy_engine(_current_lang())
    return _analyze_segments(video_id, channel, index_segments, compiled, combined)


def _run_cs(video_id: str, chat_path: str | None) -> dict | None:
    """CS = chatseeker._score_file. Return None bila file chat tak ada."""
    if not chat_path or not os.path.exists(chat_path):
        return None
    from chatseeker import _score_file

    return {"score": _score_file(Path(chat_path))}


# ==============================================================================
# HELPERS
# ==============================================================================
_CURRENT_LANG = "id"


def _current_lang() -> str:
    return _CURRENT_LANG


def _seg_sec(seg: dict) -> int:
    """Ambil detik dari segmen apa pun bentuknya (start float / sec int)."""
    if "sec" in seg:
        try:
            return int(seg["sec"])
        except (TypeError, ValueError):
            return 0
    try:
        return int(seg.get("start", 0))
    except (TypeError, ValueError):
        return 0


def _to_index_segments(segments: list) -> list[dict]:
    """Normalisasi segmen apa pun → [{sec, text}] gaya index/VTT."""
    out = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        out.append({"sec": _seg_sec(seg), "text": text})
    return out


def _json_safe(obj):
    """Konversi tuple/regex-laden objek hasil engine → struktur JSON-safe."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


# ==============================================================================
# CORE
# ==============================================================================
def capture_video(
    video_id: str,
    channel: str,
    engines: set[str],
    raw_segments: list,
    source: str,
    chat_path: str | None,
) -> dict:
    record = {
        "video_id": video_id,
        "source": source,
        "segments_raw": _json_safe(raw_segments),
        "engines": {},
    }
    results = record["engines"]

    if "e" in engines:
        try:
            results["e"] = _json_safe(_run_e(video_id, channel))
        except (Exception, SystemExit) as exc:  # noqa: BLE001 — engine bisa sys.exit saat dep absen
            results["e"] = {"error": f"{type(exc).__name__}: {exc}"}

    if "ie" in engines:
        try:
            ie = _run_ie(video_id, channel, raw_segments)
            results["ie"] = _json_safe(ie) if ie is not None else {"skipped": "tanpa segmen index"}
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            results["ie"] = {"error": f"{type(exc).__name__}: {exc}"}

    if "ae" in engines:
        try:
            ae = _run_ae(video_id, channel, raw_segments)
            results["ae"] = _json_safe(ae) if ae is not None else {"skipped": "tanpa segmen VTT"}
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            results["ae"] = {"error": f"{type(exc).__name__}: {exc}"}

    if "cs" in engines:
        try:
            cs = _run_cs(video_id, chat_path)
            results["cs"] = _json_safe(cs) if cs is not None else {"skipped": "tanpa file chat"}
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            results["cs"] = {"error": f"{type(exc).__name__}: {exc}"}

    return record


def build_document(
    channel: str,
    lang: str,
    limit: int,
    engines: set[str],
    videos: list[dict],
) -> dict:
    return {
        "meta": {
            "channel": channel,
            "lang": lang,
            "limit": limit,
            "engines": sorted(engines),
            "dedup_mode": BASELINE_DEDUP_MODE,
            "cluster_mode": BASELINE_CLUSTER_MODE,
            "captured_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "source": "yt-api",
            "tool": "baseline_capture.py",
        },
        "videos": videos,
    }


def run(args: argparse.Namespace) -> int:
    global _CURRENT_LANG
    _CURRENT_LANG = args.lang

    engines = _parse_engines(args.engines)

    if args.dry_run:
        _log("[dry-run] mode kering: tak fetch apa pun.")
        ids = fetch_video_ids(args.channel, args.limit)
        doc = build_document(args.channel, args.lang, args.limit, engines, [])
        _write_json(args.out, doc)
        _log(f"[dry-run] {len(ids)} video ID terlihat; output ditulis (videos kosong): {args.out}")
        return 0

    ids = fetch_video_ids(args.channel, args.limit)
    if not ids:
        _log("[!] Tidak ada video ID. Keluar rapi.")
        doc = build_document(args.channel, args.lang, args.limit, engines, [])
        _write_json(args.out, doc)
        return 0

    videos = []
    chat_dir = args.chat_dir
    for i, vid in enumerate(ids, 1):
        _log(f"[{i}/{len(ids)}] {vid}")
        raw, source = fetch_raw_segments(vid, args.lang)
        chat_path = os.path.join(chat_dir, f"chat_{vid}.live_chat.json") if chat_dir else None
        videos.append(
            capture_video(vid, args.channel, engines, raw, source, chat_path)
        )

    doc = build_document(args.channel, args.lang, args.limit, engines, videos)
    _write_json(args.out, doc)
    _log(f"[OK] {len(videos)} video direkam -> {args.out}")
    return 0


def _parse_engines(raw: str) -> set[str]:
    picked = {e.strip().lower() for e in raw.split(",") if e.strip()}
    unknown = picked - set(ALL_ENGINES)
    if unknown:
        raise SystemExit(f"Engine tak dikenal: {sorted(unknown)} (pilih dari {ALL_ENGINES})")
    return picked or set(ALL_ENGINES)


def _write_json(path: str, doc: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="baseline_capture.py",
        description="Fase 0: rekam input segmen + output 4 engine (E/IE/AE/CS) ke JSON.",
    )
    p.add_argument("--channel", default="", help="handle/channel_id/URL YouTube")
    p.add_argument("--lang", default="id", help="kode bahasa menu (id/en/jp/kr/in/th)")
    p.add_argument("--limit", type=int, default=20, help="jumlah video (<=0 = semua)")
    p.add_argument(
        "--engines",
        default="e,ie,ae,cs",
        help="engine dipilih, dipisah koma (e,ie,ae,cs)",
    )
    p.add_argument("--out", default="baseline_out.json", help="path file output JSON")
    p.add_argument(
        "--chat-dir",
        default="",
        help="folder berisi chat_<video_id>.live_chat.json (opsional, untuk engine cs)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="tanpa fetch berat; tulis meta + videos kosong lalu keluar rapi",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
