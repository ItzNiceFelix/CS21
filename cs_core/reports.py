"""Laporan HTML: penamaan, penyimpanan, dan daftar berkas.

Engine lama menulis `laporan_<channel>_<ddmmyyyy_hhmm>.html` ke folder config
(hidden, tidak muncul di file manager Android) lalu menghapusnya setelah
terkirim ke Discord. Tanpa webhook, file tertinggal di tempat yang tidak
ditemukan user. Modul ini menyatukan lokasi + penamaan supaya `cs21 report`
dan engine lama menunjuk folder yang sama.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import paths as _paths

__all__ = ["ReportFile", "reports_dir", "report_path", "list_reports", "prune", "latest"]

_PREFIX = "laporan_"
_SUFFIX = ".html"
_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")

def reports_dir(create: bool = True) -> Path:
    """Folder laporan (storage Android bila tersedia)."""
    if create:
        return _paths.reports_dir()
    shared = _paths.shared_storage()
    base = (shared / _paths.REPORTS_FOLDER) if shared else (Path.home() / ".cs20" / "laporan")
    return base

def _slug(text: str, limit: int = 48) -> str:
    cleaned = _SAFE_RE.sub("_", (text or "").strip()).strip("._")
    return (cleaned or "video")[:limit]

def report_path(label: str, *, when: datetime | None = None,
                folder: Path | None = None) -> Path:
    """Path laporan baru: `laporan_<label>_<ddmmyyyy_hhmm>.html`."""
    folder = folder or reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (when or datetime.now()).strftime("%d%m%Y_%H%M")
    base = folder / f"{_PREFIX}{_slug(label)}_{stamp}{_SUFFIX}"
    if not base.exists():
        return base
    # Tabrakan dalam menit yang sama: tambahkan detik.
    stamp2 = (when or datetime.now()).strftime("%d%m%Y_%H%M%S")
    return folder / f"{_PREFIX}{_slug(label)}_{stamp2}{_SUFFIX}"

@dataclass(frozen=True)
class ReportFile:
    path: Path
    size: int
    mtime: float
    label: str
    when: str

    @property
    def age_human(self) -> str:
        delta = max(0, time.time() - self.mtime)
        if delta < 3600:
            return f"{int(delta // 60)} menit lalu"
        if delta < 86400:
            return f"{int(delta // 3600)} jam lalu"
        return f"{int(delta // 86400)} hari lalu"

def _parse(path: Path) -> ReportFile | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    stem = path.name[len(_PREFIX):-len(_SUFFIX)] if path.name.startswith(_PREFIX) else path.stem
    label, _, stamp = stem.rpartition("_")
    if not label:
        label, stamp = stem, ""
    # `stamp` = `ddmmyyyy_hhmm`; label bisa mengandung '_' (nama channel).
    if "_" in label:
        head, _, tail = label.rpartition("_")
        if len(tail) == 8 and tail.isdigit():
            label = head
    when = ""
    try:
        when = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        pass
    return ReportFile(path=path, size=stat.st_size, mtime=stat.st_mtime,
                      label=label or stem, when=when)

def list_reports(folder: Path | None = None) -> list[ReportFile]:
    """Semua laporan HTML, terbaru dulu."""
    folder = folder or reports_dir(create=False)
    try:
        paths = list(folder.glob(f"{_PREFIX}*{_SUFFIX}"))
    except OSError:
        return []
    reports = [r for r in (_parse(p) for p in paths) if r is not None]
    reports.sort(key=lambda r: r.mtime, reverse=True)
    return reports

def latest(folder: Path | None = None) -> ReportFile | None:
    reports = list_reports(folder)
    return reports[0] if reports else None

def prune(keep: int = 20, folder: Path | None = None) -> int:
    """Hapus laporan terlama, sisakan `keep` terbaru. Return jumlah dihapus."""
    reports = list_reports(folder)
    if keep < 0 or len(reports) <= keep:
        return 0
    removed = 0
    for rep in reports[keep:]:
        try:
            os.remove(rep.path)
            removed += 1
        except OSError:
            continue
    return removed
