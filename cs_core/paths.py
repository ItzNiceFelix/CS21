"""Lokasi penyimpanan bersama (storage Android vs home Termux).

Masalah yang diselesaikan:

- Di PRoot `~` = `/root`, sehingga `~/storage/shared` tidak ada walau
  `/storage/emulated/0` bisa ditulis. Deteksi lama hanya melihat
  `~/storage/shared` -> selalu jatuh ke `~/.cs20` sambil mencetak peringatan.
- Peringatan itu dicetak oleh library, berkali-kali per perintah (CLI memanggil
  deteksi untuk index, lalu cache memanggil lagi). Semua diagnostik sekarang
  hanya lewat `doctor`/menu, bukan dari lapisan data.
- Beberapa root cache bisa hidup bersamaan (Termux asli vs PRoot). Root lama
  tetap **dibaca** supaya cache tidak hilang; penulisan selalu ke satu root
  primer supaya tidak bercabang lagi.

Prioritas root: `CS_DATA_DIR` > storage bersama > `~/.cs20/index_cache`.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "DATA_DIR_ENV",
    "shared_storage",
    "primary_cache_root",
    "cache_roots",
    "reports_dir",
    "describe",
]

DATA_DIR_ENV = "CS_DATA_DIR"

# Nama folder di storage bersama (dipakai engine lama juga).
SHARED_FOLDER = "CS20_Index"
REPORTS_FOLDER = "CS20_Laporan"

def _writable(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.W_OK)
    except OSError:
        return False

def shared_storage() -> Path | None:
    """Folder storage Android yang bisa ditulis, atau `None`.

    Mencoba symlink Termux (`~/storage/shared`) lebih dulu, lalu path absolut
    yang tetap ada di dalam PRoot.
    """
    for candidate in (
        Path(os.path.expanduser("~/storage/shared")),
        Path("/storage/emulated/0"),
        Path("/sdcard"),
    ):
        if _writable(candidate):
            return candidate
    return None

def _env_override() -> Path | None:
    raw = (os.environ.get(DATA_DIR_ENV) or "").strip()
    return Path(os.path.expanduser(raw)) if raw else None

def primary_cache_root() -> Path:
    """Root cache untuk penulisan (dibuat bila belum ada)."""
    override = _env_override()
    if override is not None:
        path = override
    else:
        shared = shared_storage()
        path = (shared / SHARED_FOLDER) if shared else (Path.home() / ".cs20" / "index_cache")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = Path.home() / ".cs20" / "index_cache"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback
    return path

def cache_roots() -> list[Path]:
    """Semua root cache yang mungkin berisi data (primer dulu, tanpa duplikat)."""
    candidates: list[Path] = []
    override = _env_override()
    if override is not None:
        candidates.append(override)
    candidates.append(primary_cache_root())

    shared = shared_storage()
    if shared is not None:
        candidates.append(shared / SHARED_FOLDER)
    candidates.append(Path("/storage/emulated/0") / SHARED_FOLDER)
    candidates.append(Path.home() / ".cs20" / "index_cache")

    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_dir():
                out.append(path)
        except OSError:
            continue
    return out

def reports_dir() -> Path:
    """Folder laporan HTML: storage bersama bila ada, else `<config>/laporan`."""
    shared = shared_storage()
    base = (shared / REPORTS_FOLDER) if shared else (Path.home() / ".cs20" / "laporan")
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base

def describe() -> str:
    """Ringkasan satu baris untuk menu/doctor."""
    shared = shared_storage()
    primary = primary_cache_root()
    if shared is None:
        return f"{primary} (storage Android tidak tersedia)"
    return f"{primary} (storage Android: {shared})"
