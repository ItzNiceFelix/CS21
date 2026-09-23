"""Cache transcript gzip JSONL (Fase 4).

- Lokasi: `{detect_cache_root()}/transcripts/{video_id}.{lang}.jsonl.gz`.
- Baris pertama = header meta `{"_meta": {...}, ...}`; sisanya = segmen.
- Normalisasi key lang (`id-ID` -> `id`) supaya `id`/`id-ID` berbagi cache.
- TTL default 30 hari (`cs_core.config.CACHE_TTL_DAYS`).
- Atomic write: tulis `.tmp` lalu `os.replace` (pola `save_json_safe` parser).
- `compresslevel=1` (kompromi kecepatan/ukuran di ARM).
- Format-version mismatch -> miss (tulis ulang).

Pure stdlib: gzip, json, os, time, pathlib.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path

from .config import CACHE_TTL_DAYS_ENV, DEFAULT_CACHE_TTL_DAYS

__all__ = [
    "CACHE_FORMAT_VERSION",
    "SUBDIR",
    "norm_lang",
    "cache_root",
    "cache_path",
    "read",
    "read_meta",
    "write",
    "purge",
    "gc",
]

CACHE_FORMAT_VERSION = 1
SUBDIR = "transcripts"

def norm_lang(code: str) -> str:
    """Normalisasi kode bahasa ke key cache: `id-ID` -> `id`, `EN-us` -> `en`."""
    return (code or "").strip().split("-")[0].lower()

def cache_root(root=None) -> Path:
    """Root cache + subdir `transcripts/` (dibuat bila belum ada)."""
    if root is None:
        root = _detect_cache_root()
    path = Path(root) / SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path

def _detect_cache_root() -> str:
    """Delegate ke `detect_cache_root()` engine lama; fallback lokal.

    Import lazy: `cs20_index_parser` punya dependensi (rich/subprocess) yang
    tidak selalu tersedia di lingkungan inti/test.
    """
    try:
        from cs20_index_parser import detect_cache_root as _legacy
        return _legacy()
    except Exception:
        shared = os.path.expanduser("~/storage/shared")
        if os.path.isdir(shared):
            base = os.path.join(shared, "CS20_Index")
        else:
            base = os.path.expanduser("~/.cs20/index_cache")
        os.makedirs(base, exist_ok=True)
        return base

def _ttl_sec(ttl_days) -> int:
    if ttl_days is None:
        raw = (os.environ.get(CACHE_TTL_DAYS_ENV) or "").strip()
        try:
            ttl_days = int(raw)
        except ValueError:
            ttl_days = DEFAULT_CACHE_TTL_DAYS
        if ttl_days <= 0:
            ttl_days = DEFAULT_CACHE_TTL_DAYS
    return int(ttl_days) * 86400

def cache_path(video_id: str, lang: str, root=None) -> Path:
    """Path file cache untuk `(video_id, lang)`."""
    return cache_root(root) / f"{video_id}.{norm_lang(lang)}.jsonl.gz"

def read(video_id: str, lang: str, root=None, ttl_days=None):
    """Baca cache. Return `list[dict]` segmen, atau `None` bila miss.

    Miss bila: file tidak ada, TTL lewat, versi format beda, header rusak,
    atau tidak ada segmen valid. Baris rusak di-skip, bukan fatal.
    """
    path = cache_path(video_id, lang, root)
    if not path.is_file():
        return None

    try:
        age = time.time() - path.stat().st_mtime
        if age > _ttl_sec(ttl_days if ttl_days is not None else None):
            return None
    except OSError:
        return None

    segments = []
    meta = None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue  # baris rusak: skip, jangan jatuhkan seluruh cache
                if not isinstance(obj, dict):
                    continue
                if "_meta" in obj:
                    meta = obj["_meta"]
                    continue
                seg = obj.get("seg")
                if isinstance(seg, dict) and "sec" in seg and "text" in seg:
                    segments.append({"sec": seg["sec"], "text": seg["text"]})
    except (OSError, EOFError):
        return None

    if not isinstance(meta, dict) or meta.get("v") != CACHE_FORMAT_VERSION:
        return None  # format-version mismatch / header hilang -> miss
    if meta.get("id") and meta["id"] != video_id:
        return None
    if not segments:
        return None
    return segments

def write(video_id: str, lang: str, segments, *, source: str, root=None) -> Path:
    """Tulis cache atomic (gzip JSONL). Return path.

    Header meta baris pertama: `v,id,lang,source,fetched_at,lang_requested`.
    """
    path = cache_path(video_id, lang, root)
    header = {
        "_meta": {
            "v": CACHE_FORMAT_VERSION,
            "id": video_id,
            "lang": norm_lang(lang),
            "source": source,
            "fetched_at": int(time.time()),
            "lang_requested": [lang],
        }
    }

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=1) as fh:
            fh.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
            for seg in segments or []:
                sec = seg.get("sec", seg.get("start", 0))
                text = seg.get("text", "")
                fh.write(json.dumps(
                    {"seg": {"sec": sec, "text": text}},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ))
                fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
    return path

def _match(path: Path, video_id=None, lang=None, channel=None) -> bool:
    stem = path.name
    if not stem.endswith(".jsonl.gz"):
        return False
    parts = stem[: -len(".jsonl.gz")].rsplit(".", 1)
    if len(parts) != 2:
        return False
    vid, file_lang = parts
    if video_id is not None and vid != video_id:
        return False
    if lang is not None and file_lang != norm_lang(lang):
        return False
    if channel is not None:
        meta = read_meta(path)
        if not meta or meta.get("channel") != channel:
            return False
    return True

def read_meta(path):
    """Baca header meta dari file cache (None bila rusak/tidak ada)."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict) and "_meta" in obj:
                    return obj["_meta"]
                return None
    except Exception:
        return None
    return None

def purge(video_id=None, lang=None, channel=None, all=False, max_age_days=None, root=None) -> int:
    """Hapus file cache yang cocok. Return jumlah file dihapus.

    `all=True` abaikan filter video/lang (channel tetap dihormati bila diberi).
    `max_age_days` hanya hapus file lebih tua dari itu.
    """
    base = cache_root(root)
    removed = 0
    cutoff = None
    if max_age_days is not None:
        cutoff = time.time() - int(max_age_days) * 86400

    for path in base.glob("*.jsonl.gz"):
        if not all:
            if not _match(path, video_id=video_id, lang=lang, channel=channel):
                continue
        elif channel is not None:
            if not _match(path, channel=channel):
                continue
        if cutoff is not None:
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed

def gc(root=None, ttl_days=None) -> int:
    """Sapu file lebih tua dari TTL. Return jumlah file dihapus.

    `ttl_days=None` -> pakai TTL default/env (BUKAN 0). Hindari `gc()` tanpa
    argumen menghapus seluruh cache (bug: cutoff=None = purge semua).
    """
    if ttl_days is None:
        ttl_days = _ttl_sec(None) // 86400
    return purge(all=True, max_age_days=ttl_days, root=root)
