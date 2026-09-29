"""Integrasi Termux (Android) — semua opsional, tidak pernah fatal.

Setiap fungsi mengembalikan `True`/`False` dan **tidak melempar exception**:
kalau binary `termux-*` tidak ada (Termux:API belum dipasang) atau kita jalan
di proot/desktop, semuanya jadi no-op senyap.

Dipakai menu untuk: cegah Android mematikan proses saat batch (`wake_lock`),
notifikasi + getar saat selesai (`notify`), dan buka laporan HTML (`open_file`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

__all__ = [
    "IS_TERMUX",
    "have",
    "wake_lock",
    "wake_unlock",
    "wake_lock_ctx",
    "notify",
    "toast",
    "open_file",
    "open_url",
    "vibrate",
]

# Deteksi Termux asli (bukan proot): PREFIX + folder usr milik Termux.
_TERMUX_PREFIX = "/data/data/com.termux/files/usr"
IS_TERMUX: bool = bool(os.environ.get("TERMUX_VERSION")) or (
    os.path.isdir(_TERMUX_PREFIX) and os.environ.get("PREFIX", "").startswith(_TERMUX_PREFIX)
)

def have(binary: str) -> bool:
    """True bila binary ada di PATH."""
    return shutil.which(binary) is not None

def _run(cmd: list[str], timeout: float = 5.0) -> bool:
    """Jalankan perintah pendek; senyap bila gagal/hilang.

    Hasil pertama di-cache per binary: kalau gagal sekali (mis. Termux:API
    tidak terpasang / jalan di proot), panggilan berikutnya langsung `False`
    tanpa menunggu timeout.
    """
    name = cmd[0]
    if _UNAVAILABLE.get(name):
        return False
    if not have(name):
        _UNAVAILABLE[name] = True
        return False
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except Exception:
        _UNAVAILABLE[name] = True
        return False
    if proc.returncode != 0:
        # Exit non-zero (mis. app Termux:API tidak merespons) -> jangan ulangi.
        _UNAVAILABLE[name] = True
        return False
    return True

# binary yang sudah terbukti tidak bisa dipakai di sesi ini.
_UNAVAILABLE: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# wake lock (batch panjang tidak dibunuh Android)
# ---------------------------------------------------------------------------
# Timeout pendek: kalau app Termux:API tidak merespons, kita tidak boleh
# menahan start batch. Hasilnya di-cache, jadi hanya sekali menunggu.
_WAKE_TIMEOUT = 2.0

def wake_lock() -> bool:
    return _run(["termux-wake-lock"], timeout=_WAKE_TIMEOUT)

def wake_unlock() -> bool:
    return _run(["termux-wake-unlock"], timeout=_WAKE_TIMEOUT)

@contextmanager
def wake_lock_ctx(enabled: bool = True):
    """`with wake_lock_ctx(): ...` — unlock otomatis walau ada error."""
    locked = wake_lock() if enabled else False
    try:
        yield locked
    finally:
        if locked:
            wake_unlock()

# ---------------------------------------------------------------------------
# notifikasi
# ---------------------------------------------------------------------------
def notify(
    title: str,
    body: str = "",
    *,
    vibrate: bool = False,
    sound: bool = False,
    priority: str = "default",
    ongoing: bool = False,
) -> bool:
    """Kirim notifikasi Android (butuh paket `termux-api` + app Termux:API)."""
    cmd = ["termux-notification", "--title", title, "--priority", priority]
    if body:
        cmd += ["--content", body]
    if vibrate:
        cmd += ["--vibrate", "300,200,300"]
    if sound:
        cmd += ["--sound"]
    if ongoing:
        cmd += ["--ongoing"]
    return _run(cmd)

def toast(message: str, *, short: bool = True) -> bool:
    cmd = ["termux-toast"]
    if short:
        cmd += ["-s"]
    cmd += [message]
    return _run(cmd)

def vibrate(ms: int = 400) -> bool:
    return _run(["termux-vibrate", "-d", str(ms), "-f"])

def open_file(path: str | Path) -> bool:
    """Buka file (laporan HTML) dengan aplikasi default Android."""
    p = Path(path)
    if not p.is_file():
        return False
    if have("termux-open"):
        return _run(["termux-open", "--content-type", "text/html", str(p)])
    return False

def open_url(url: str) -> bool:
    if have("termux-open-url"):
        return _run(["termux-open-url", url])
    return False

def clipboard_set(text: str) -> bool:
    """Salin ke clipboard Android (dipakai untuk menyalin ID video)."""
    if not have("termux-clipboard-set"):
        return False
    try:
        subprocess.run(
            ["termux-clipboard-set"],
            input=text.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return True
    except Exception:
        return False

def ram_available_mb() -> int:
    """RAM tersedia (MB) dari /proc/meminfo; 0 bila tak terbaca."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0

def suggest_jobs() -> int:
    """Jumlah worker aman berdasar RAM (HP kelas menengah)."""
    ram = ram_available_mb()
    if ram <= 0:
        return 4
    if ram < 400:
        return 2
    if ram < 900:
        return 3
    if ram < 1800:
        return 4
    return 6
