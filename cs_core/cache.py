"""Cache transcript gzip JSONL (Fase 4).

- Lokasi tulis: `{paths.primary_cache_root()}/transcripts/{video_id}.{lang}.jsonl.gz`
  (`CS_DATA_DIR` > storage bersama Android > `~/.cs20/index_cache`).
- Lokasi baca: **semua** root yang pernah dipakai, primer dulu. Cache lama di
  home PRoot/Termux tetap terbaca walau lokasi primer berpindah.
- Baris pertama = header meta `{"_meta": {...}, ...}`; sisanya = segmen.
- Normalisasi key lang (`id-ID` -> `id`) supaya `id`/`id-ID` berbagi cache.
- TTL default 30 hari (`cs_core.config.CACHE_TTL_DAYS`).
- Atomic write: tulis `.tmp` lalu `os.replace` (pola `save_json_safe` parser).
- `compresslevel=1` (kompromi kecepatan/ukuran di ARM).
- Format-version mismatch -> miss (tulis ulang).

Tanpa diagnostik: modul ini tidak mencetak apa pun. Peringatan storage adalah
tugas `doctor`/menu, bukan lapisan data (dulu tercetak 2x per perintah).

Pure stdlib: gzip, json, os, time, pathlib.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path

from . import paths as _paths
from .config import CACHE_TTL_DAYS_ENV, DEFAULT_CACHE_TTL_DAYS

__all__ = [
    "CACHE_FORMAT_VERSION",
    "SUBDIR",
    "norm_lang",
    "cache_root",
    "cache_path",
    "cache_paths",
    "all_cache_dirs",
    "read",
    "read_meta",
    "write",
    "purge",
    "gc",
    "stats",
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

def all_cache_dirs(root=None) -> list[Path]:
    """Semua folder `transcripts/` yang ada: primer dulu, tanpa duplikat.

    Root eksplisit (`root`) -> hanya itu. Tanpa root -> tulis ke primer
    (`paths.primary_cache_root`) tapi **baca** dari semua root yang pernah
    dipakai (Termux asli, PRoot, storage bersama), supaya cache lama tidak
    seolah hilang setelah lokasi primer berubah.
    """
    if root is not None:
        return [Path(root) / SUBDIR]
    out: list[Path] = []
    for base in _paths.cache_roots():
        candidate = base / SUBDIR
        try:
            if candidate.is_dir():
                out.append(candidate)
        except OSError:
            continue
    primary = cache_root()
    if primary not in out:
        out.insert(0, primary)
    return out

def cache_paths(video_id: str, lang: str, root=None) -> list[Path]:
    """Semua path yang mungkin menyimpan cache video+lang ini (primer dulu)."""
    name = f"{video_id}.{norm_lang(lang)}.jsonl.gz"
    return [folder / name for folder in all_cache_dirs(root)]

def _detect_cache_root() -> str:
    """Lokasi primer: `CS_DATA_DIR` > storage bersama > home Termux."""
    return str(_paths.primary_cache_root())

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
    """Path file cache untuk `(video_id, lang)` di root primer."""
    return cache_root(root) / f"{video_id}.{norm_lang(lang)}.jsonl.gz"

def read(video_id: str, lang: str, root=None, ttl_days=None):
    """Baca cache dari root primer lalu root lain. `None` bila semua miss.

    Miss bila: file tidak ada, TTL lewat, versi format beda, header rusak,
    atau tidak ada segmen valid. Baris rusak di-skip, bukan fatal.
    """
    for path in cache_paths(video_id, lang, root):
        segments = _read_path(path, video_id, ttl_days)
        if segments is not None:
            return segments
    return None

def _read_path(path: Path, video_id: str, ttl_days=None):
    """Baca satu file cache; `None` bila miss/rusak."""
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

def write(video_id: str, lang: str, segments, *, source: str, root=None,
          channel: str = "") -> Path:
    """Tulis cache atomic (gzip JSONL). Return path.

    Header meta baris pertama: `v,id,lang,source,fetched_at,lang_requested`
    (+ `channel` bila diketahui). Tanpa `channel`, filter `--channel` pada
    `purge`/`search` tidak pernah cocok karena `_match` membandingkannya
    dengan field yang tidak pernah ditulis.
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
    if channel:
        header["_meta"]["channel"] = channel

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
    """Hapus file cache yang cocok di SEMUA root. Return jumlah file dihapus.

    `all=True` abaikan filter video/lang (channel tetap dihormati bila diberi).
    `max_age_days` hanya hapus file lebih tua dari itu.
    """
    removed = 0
    cutoff = None
    if max_age_days is not None:
        cutoff = time.time() - int(max_age_days) * 86400

    for base in all_cache_dirs(root):
        removed += _purge_dir(base, video_id=video_id, lang=lang, channel=channel,
                              all=all, cutoff=cutoff)
    return removed

def _purge_dir(base: Path, *, video_id, lang, channel, all: bool, cutoff) -> int:
    removed = 0
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

def stats(root=None) -> dict:
    """Ringkasan isi cache di semua root (primer ditandai)."""
    primary = cache_root(root)
    rows = []
    total_files = 0
    total_bytes = 0
    for folder in all_cache_dirs(root):
        files = list(folder.glob("*.jsonl.gz"))
        size = 0
        for path in files:
            try:
                size += path.stat().st_size
            except OSError:
                continue
        total_files += len(files)
        total_bytes += size
        rows.append({
            "dir": str(folder),
            "primary": folder == primary,
            "files": len(files),
            "bytes": size,
        })
    return {
        "dir": str(primary),
        "files": total_files,
        "bytes": total_bytes,
        "roots": rows,
    }

def recent(limit: int = 20, root=None) -> list[dict]:
    """Cache terbaru (untuk menu "video terakhir"). Terbaru dulu, dedup video."""
    seen: set[str] = set()
    rows: list[dict] = []
    candidates: list[Path] = []
    for folder in all_cache_dirs(root):
        try:
            candidates.extend(folder.glob("*.jsonl.gz"))
        except OSError:
            continue
    for path in sorted(candidates, key=lambda p: _safe_mtime(p), reverse=True):
        stem = path.name[: -len(".jsonl.gz")]
        video_id, _, lang = stem.partition(".")
        key = f"{video_id}.{lang}"
        if not video_id or key in seen:
            continue
        seen.add(key)
        meta = read_meta(path) or {}
        rows.append({
            "video_id": video_id,
            "lang": lang,
            "path": str(path),
            "mtime": _safe_mtime(path),
            "fetched_at": meta.get("fetched_at") or 0,
            "source": meta.get("source") or "",
        })
        if len(rows) >= limit:
            break
    return rows

def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
