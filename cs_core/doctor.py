"""Preflight `cs21 doctor` — cek kesiapan Termux/Android, opsi perbaikan.

Semua pemeriksaan murni lokal + satu tes jaringan singkat. Keluar dengan
`ExitCode.FAIL` bila ada masalah **fatal**; peringatan tidak menggagalkan.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths as _paths
from . import settings as _settings
from . import termux as _termux
from .errors import ExitCode

__all__ = ["run_doctor", "collect", "Report", "Check"]

FATAL = "fatal"
WARN = "warn"
INFO = "info"

@dataclass
class Check:
    name: str
    status: str          # ok | warn | fatal
    detail: str = ""
    fix: str = ""        # perintah saran perbaikan (string shell)
    fixable: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok"

@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def fatal(self) -> list[Check]:
        return [c for c in self.checks if c.status == FATAL]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]

# ---------------------------------------------------------------------------
# util
# ---------------------------------------------------------------------------
def _module_ok(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

def _has(binary: str) -> bool:
    return shutil.which(binary) is not None

def _shared_storage() -> Path | None:
    """Folder storage Android yang bisa ditulis (satu sumber: `paths`)."""
    return _paths.shared_storage()

def _webhook_file() -> Path:
    return _settings.config_dir() / ".webhook_injected"

def _read_webhooks() -> dict[str, str]:
    """Baca webhook dari file inject (tanpa mengeksekusi shell)."""
    path = _webhook_file()
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out

def _net_ok(timeout: float = 6.0) -> bool:
    for host, port in (("www.youtube.com", 443), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False

def _youtube_ok(timeout: float = 10.0) -> bool:
    """HEAD ringan ke YouTube; bedakan 'tak ada internet' vs 'diblokir'."""
    try:
        req = urllib.request.Request(
            "https://www.youtube.com/",
            method="HEAD",
            headers={"User-Agent": "Mozilla/5.0 (Android 13; Termux)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False

def _probe_rapidfuzz() -> tuple[bool, bool]:
    """Return `(terpasang, punya_ekstensi_native)`."""
    try:
        import rapidfuzz  # noqa: F401
    except Exception:
        return False, False
    base = Path(getattr(rapidfuzz, "__file__", "")).parent
    try:
        native = any(base.rglob("*.so"))
    except OSError:
        native = False
    return True, native

# ---------------------------------------------------------------------------
# pemeriksaan
# ---------------------------------------------------------------------------
def collect(*, check_network: bool = True) -> Report:
    rep = Report()
    repo = _settings.repo_root()
    cfg = _settings.config_dir()

    # 1. Python
    py = sys.version_info
    rep.add(Check(
        "python",
        FATAL if py < (3, 10) else INFO,
        f"{py.major}.{py.minor}.{py.micro} ({sys.executable})",
        fix="pkg install python",
        fixable=py < (3, 10),
    ))

    # 2. yt-dlp — hanya dipakai Index Mode + listing channel. `analyze`, `search`,
    #    `cache` jalan penuh tanpa ini, jadi TIDAK boleh menggagalkan preflight.
    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        version = ""
        try:
            out = subprocess.run([ytdlp, "--version"], capture_output=True,
                                 text=True, timeout=15)
            version = (out.stdout or "").strip().splitlines()[0] if out.stdout else ""
        except Exception:
            pass
        rep.add(Check("yt-dlp", INFO, f"{ytdlp} {version}".strip()))
    else:
        rep.add(Check("yt-dlp", WARN,
                      "tidak ditemukan — Index Mode & scan channel butuh ini",
                      fix="pkg install yt-dlp", fixable=True))

    # 3. modul python
    for mod, fatal, hint in (
        ("youtube_transcript_api", FATAL, "pip install youtube-transcript-api --break-system-packages"),
        ("requests", WARN, "pip install requests --break-system-packages"),
        ("rich", WARN, "pip install rich --break-system-packages"),
    ):
        ok = _module_ok(mod)
        rep.add(Check(
            f"python:{mod}",
            INFO if ok else fatal,
            "terpasang" if ok else "belum terpasang",
            fix=hint,
            fixable=not ok,
        ))

    # 4. prompt_toolkit (opsional, tapi user minta dipakai)
    ptk = _module_ok("prompt_toolkit")
    rep.add(Check(
        "python:prompt_toolkit",
        INFO if ptk else WARN,
        "terpasang (menu panah aktif)" if ptk else "belum terpasang (menu pakai angka)",
        fix="pip install prompt_toolkit --break-system-packages",
        fixable=not ptk,
    ))

    # 5. rapidfuzz: tanpa ekstensi native = tidak berguna di Termux
    rf_installed, rf_native = _probe_rapidfuzz()
    if not rf_installed:
        rep.add(Check("rapidfuzz", INFO, "tidak dipakai (fuzzy pakai difflib stdlib)"))
    elif rf_native:
        rep.add(Check("rapidfuzz", INFO, "terpasang dengan ekstensi native"))
    else:
        rep.add(Check(
            "rapidfuzz", WARN,
            "terpasang TAPI tanpa ekstensi native (tidak mempercepat apa pun)",
            fix="pip uninstall -y rapidfuzz",
            fixable=True,
        ))

    # 6. curl / termux-api
    rep.add(Check("curl", INFO if _has("curl") else WARN,
                  shutil.which("curl") or "tidak ada",
                  fix="pkg install curl", fixable=not _has("curl")))
    api_bins = [b for b in ("termux-wake-lock", "termux-notification", "termux-open")
                if _has(b)]
    rep.add(Check(
        "termux-api",
        INFO if "termux-notification" in "".join(api_bins) else WARN,
        f"{len(api_bins)} binary terdeteksi: {', '.join(api_bins) or '—'}",
        fix="pkg install termux-api  (lalu pasang app Termux:API)",
        fixable="termux-notification" not in "".join(api_bins),
    ))

    # 7. storage Android
    shared = _shared_storage()
    rep.add(Check(
        "storage",
        INFO if shared else WARN,
        str(shared) if shared else "storage Android tidak terdeteksi — data di Termux home",
        fix="termux-setup-storage",
        fixable=not shared,
    ))

    # 7b. cache: root primer + root lain yang masih dibaca (anti split-brain)
    primary = _paths.primary_cache_root()
    others = [p for p in _paths.cache_roots() if p != primary]
    detail = str(primary)
    if others:
        detail += f" (+{len(others)} root lama dibaca: {', '.join(str(p) for p in others)})"
    rep.add(Check("cache", INFO, detail))

    # 8. config dir
    try:
        cfg.mkdir(parents=True, exist_ok=True)
        probe = cfg / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        rep.add(Check("config-dir", INFO, str(cfg)))
    except OSError as exc:
        rep.add(Check("config-dir", FATAL, f"tidak bisa ditulis: {exc}",
                      fix=f"periksa izin {cfg}"))

    # 9. cookies
    cookies = Path(os.environ.get("CS_COOKIES") or (cfg / "cookies.txt"))
    if cookies.is_file():
        size = cookies.stat().st_size
        rep.add(Check("cookies", INFO, f"{cookies} ({size} B)"))
    else:
        rep.add(Check("cookies", WARN, f"belum ada: {cookies}",
                      fix="bash setup_cookies.sh", fixable=True))

    # 10. webhook
    hooks = _read_webhooks()
    found = [k for k, v in hooks.items() if v.startswith("http")]
    if found:
        rep.add(Check("webhook", INFO, f"{', '.join(found)} siap"))
    else:
        rep.add(Check("webhook", WARN, "belum di-inject",
                      fix="bash inject_webhook.sh", fixable=True))

    # 11. engine
    missing = [name for name in ("cs20_engine.py", "cs20_index_engine.py",
                                 "cs20_age_engine.py", "cs20_autodrive_engine.py",
                                 "chatseeker.py")
               if not (repo / name).is_file()]
    rep.add(Check(
        "engine",
        FATAL if missing else INFO,
        f"lengkap di {repo}" if not missing else f"hilang: {', '.join(missing)}",
        fix="jalankan cs21 dari folder repo CS21",
    ))

    # 12. RAM
    ram = _termux.ram_available_mb()
    if ram:
        status = WARN if ram < 350 else INFO
        rep.add(Check("ram", status, f"{ram} MB tersedia (saran jobs: {_termux.suggest_jobs()})",
                      fix="tutup aplikasi lain" if status == WARN else ""))
    else:
        rep.add(Check("ram", INFO, "tidak terbaca"))

    # 13. jaringan
    if not check_network:
        rep.add(Check("jaringan", INFO, "dilewati (offline)"))
    elif _net_ok():
        if _youtube_ok():
            rep.add(Check("jaringan", INFO, "internet + YouTube OK"))
        else:
            rep.add(Check("jaringan", WARN, "internet jalan, YouTube tidak bisa diakses",
                          fix="cek DNS/VPN, atau tunggu kalau sedang rate limit"))
    else:
        rep.add(Check("jaringan", FATAL, "tidak ada koneksi internet",
                      fix="cek WiFi/data seluler"))

    return rep

# ---------------------------------------------------------------------------
# perbaikan
# ---------------------------------------------------------------------------
_FIX_COMMANDS: dict[str, list[list[str]]] = {
    "yt-dlp": [["pkg", "install", "-y", "yt-dlp"]],
    "curl": [["pkg", "install", "-y", "curl"]],
    "python:youtube_transcript_api": [["pip", "install", "--break-system-packages", "-q",
                                       "youtube-transcript-api"]],
    "python:requests": [["pip", "install", "--break-system-packages", "-q", "requests"]],
    "python:rich": [["pip", "install", "--break-system-packages", "-q", "rich"]],
    "python:prompt_toolkit": [["pip", "install", "--break-system-packages", "-q",
                               "prompt_toolkit"]],
    "rapidfuzz": [["pip", "uninstall", "-y", "-q", "rapidfuzz"]],
    "termux-api": [["pkg", "install", "-y", "termux-api"]],
    "storage": [["termux-setup-storage"]],
    "cookies": [["bash", str(_settings.repo_root() / "setup_cookies.sh")]],
    "webhook": [["bash", str(_settings.repo_root() / "inject_webhook.sh")]],
}

# Perbaikan yang butuh terminal (tidak dijalankan otomatis saat pipe/cron).
_INTERACTIVE_ONLY = {"cookies"}

def _apply_fix(check: Check, *, interactive: bool) -> tuple[bool, str]:
    cmds = _FIX_COMMANDS.get(check.name)
    if not cmds:
        return False, "tidak ada perbaikan otomatis"

    if check.name in _INTERACTIVE_ONLY and not interactive:
        return False, f"butuh terminal — jalankan manual: {check.fix}"

    if interactive and check.name == "storage":
        # termux-setup-storage membuka dialog izin Android.
        print("    (dialog izin Android akan muncul — ketuk 'Allow')")

    for cmd in cmds:
        if not _has(cmd[0]):
            return False, f"'{cmd[0]}' tidak tersedia"
        if interactive:
            try:
                answer = input(f"    jalankan: {' '.join(cmd)} ? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False, "dibatalkan"
            if answer and answer not in ("y", "ya", "yes"):
                return False, "dilewati"
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"gagal: {exc}"
        if proc.returncode != 0:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
            return False, f"exit {proc.returncode}: {tail[-1] if tail else ''}"
    return True, "selesai"

# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
_MARK = {"ok": "✓", "warn": "!", "fatal": "✗", "info": "·"}

def _print_report(rep: Report) -> None:
    print("cs21 doctor — preflight Termux")
    print("=" * 52)
    for check in rep.checks:
        mark = _MARK.get(check.status, "·")
        print(f"  {mark} {check.name:<28} {check.detail}")
        if check.status != "info" and check.fix:
            print(f"      ↳ saran: {check.fix}")
    print("=" * 52)
    if rep.fatal:
        print(f"  {len(rep.fatal)} masalah fatal — perbaiki dulu sebelum memakai cs21")
    elif rep.warned:
        print(f"  {len(rep.warned)} peringatan — cs21 tetap bisa jalan")
    else:
        print("  semua siap ✓")

def run_doctor(*, fix: bool = False, as_json: bool = False) -> int:
    interactive = sys.stdin.isatty() and not as_json
    rep = collect(check_network=not as_json)

    if fix:
        targets = [c for c in rep.checks if not c.ok and c.fixable]
        if not as_json and targets:
            print(f"cs21 doctor --fix — {len(targets)} item akan diperbaiki\n")
        for check in targets:
            if not as_json:
                print(f"  → {check.name}: {check.detail}")
            ok, note = _apply_fix(check, interactive=interactive)
            if not as_json:
                print(f"    {'✓' if ok else '✗'} {note}")
        if targets:
            rep = collect(check_network=not as_json)  # verifikasi ulang

    if as_json:
        payload = {
            "ok": not rep.fatal,
            "fatal": len(rep.fatal),
            "warnings": len(rep.warned),
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail,
                 "fix": c.fix, "fixable": c.fixable}
                for c in rep.checks
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_report(rep)

    return int(ExitCode.OK) if not rep.fatal else int(ExitCode.FAIL)
