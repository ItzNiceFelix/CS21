"""Menu interaktif `python -m cs_core` (tanpa argumen).

Dioptimalkan untuk Android/Termux: cukup tekan angka, tak perlu ketik flag.
TANPA `rich` (stdlib print + input) supaya ringan dan aman di terminal sempit.

Masuk: `python -m cs_core` (tanpa subcommand) -> menu ini.
Subcommand eksplisit (`scan`, `analyze`, ...) tetap jalan seperti biasa.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__all__ = ["run_menu", "load_saved_channels", "remember_channel"]

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent

# Bahasa default sesi menu (dipilih sekali di awal).
_LANGS = {
    "1": ("id", "Indonesia"),
    "2": ("en", "English"),
    "3": ("jp", "Jepang"),
    "4": ("kr", "Korea"),
    "5": ("in", "Hindi/India"),
    "6": ("th", "Thailand"),
}


# ---------------------------------------------------------------------------
# util I/O
# ---------------------------------------------------------------------------
def _line(width: int = 52) -> str:
    return "=" * width


class _MenuExit(Exception):
    """EOF/Ctrl+C saat input -> keluar bersih (bukan loop tak henti)."""


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        # stdin habis (cron/pipe) atau user Ctrl+C -> hentikan menu.
        raise _MenuExit()


def _pause():
    _ask("\n  [Enter] lanjut...")


def _clear():
    # Hanya bersihkan layar bila stdout TTY nyata. Di pipe/cron,
    # memanggil clear/cls bisa menggantung atau mengotori output.
    if not sys.stdout.isatty():
        return
    cmd = "cls" if os.name == "nt" else "clear"
    try:
        subprocess.call(cmd, shell=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# daftar channel tersimpan (biar tak perlu ngetik di HP)
# ---------------------------------------------------------------------------
def _saved_channels_path() -> Path:
    return Path(".cs20") / "channels.txt"


def load_saved_channels(config_dir: str = ".cs20") -> list[str]:
    """Gabung channel dari channels.txt + checkpoint + log engine.

    Urutan terjaga, dedup. Return list nama channel (tanpa duplikat).
    """
    seen: list[str] = []
    seen_set: set[str] = set()

    def _add(name: str):
        name = (name or "").strip().lstrip("@")
        if name and name not in seen_set:
            seen_set.add(name)
            seen.append(name)

    # 1) channels.txt (paling eksplisit)
    for base in (Path(config_dir), Path(".cs20")):
        f = base / "channels.txt"
        if f.is_file():
            try:
                for ln in f.read_text(encoding="utf-8").splitlines():
                    _add(ln)
            except OSError:
                pass

    # 2) checkpoint dir: {channel}.checkpoint
    for cp_dir in (Path(config_dir) / "checkpoints", Path(".cs20") / "checkpoints"):
        if cp_dir.is_dir():
            for f in sorted(cp_dir.glob("*.checkpoint")):
                _add(f.stem)

    # 3) index_cache: {channel}/meta.json
    for root in (Path.home() / ".cs20" / "index_cache",
                 Path.home() / "storage" / "shared" / "CS20_Index"):
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and (d / "meta.json").is_file():
                    _add(d.name)

    return seen


def remember_channel(channel: str, config_dir: str = ".cs20") -> None:
    """Simpan channel ke channels.txt (dipanggil tiap scan) supaya lain kali
    tinggal dipilih nomor."""
    channel = (channel or "").strip().lstrip("@")
    if not channel:
        return
    try:
        base = Path(config_dir)
        base.mkdir(parents=True, exist_ok=True)
        f = base / "channels.txt"
        existing = set()
        if f.is_file():
            existing = {ln.strip().lstrip("@") for ln in
                        f.read_text(encoding="utf-8").splitlines() if ln.strip()}
        if channel not in existing:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(channel + "\n")
    except OSError:
        pass


def _pick_channel(config_dir: str) -> str:
    """Tampilkan daftar channel tersimpan; user pilih nomor atau ketik baru."""
    saved = load_saved_channels(config_dir)
    print()
    if saved:
        print("  Channel tersimpan:")
        for i, ch in enumerate(saved[:12], 1):
            print(f"   {i}. @{ch}")
        print("   0. Ketik channel baru")
        print()
        choice = _ask("  pilih nomor: ")
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= min(len(saved), 12):
                return saved[n - 1]
            if n == 0:
                return _ask("  channel (handle / UCxxx): ").lstrip("@")
            print("  nomor tak valid, ketik manual.")
        elif choice:
            # user langsung ketik nama channel
            return choice.lstrip("@")
    else:
        print("  (belum ada channel tersimpan)")
    return _ask("  channel (handle / UCxxx): ").lstrip("@")


# ---------------------------------------------------------------------------
# subprocess ke engine lama (non-import; hindari rich di proses ini)
# ---------------------------------------------------------------------------
def _run_engine(script: str, args: list) -> int:
    path = _REPO_ROOT / script
    if not path.is_file():
        print(f"  engine tidak ditemukan: {script}")
        return 1
    try:
        return subprocess.call([sys.executable, str(path), *args], cwd=str(_REPO_ROOT))
    except KeyboardInterrupt:
        print("\n  dihentikan.")
        return 130


# ---------------------------------------------------------------------------
# aksi menu
# ---------------------------------------------------------------------------
def _act_scan(lang: str, config_dir: str) -> None:
    channel = _pick_channel(config_dir)
    if not channel:
        print("  channel kosong, batal.")
        return
    remember_channel(channel, config_dir)

    limit = _ask("  berapa video terakhir? (Enter=20): ") or "20"
    if not limit.isdigit():
        limit = "20"
    ui = _ask("  pakai dashboard Live? (y/N): ").lower() in ("y", "ya")

    args = [
        "--channel", channel,
        "--limit", limit,
        "--lang", lang,
        "--executor", "menu",
        "--content-type", "all",
        "--jobs", "4",
        "--mode", "pantau" if ui else "plain",
        "--config-dir", config_dir,
        "--checkpoint-dir", str(Path(config_dir) / "checkpoints"),
        "--webhook-url", os.environ.get("CS_WEBHOOK", ""),
    ]
    _run_engine("cs20_engine.py", args)
    _pause()


def _act_analyze(lang: str, config_dir: str) -> None:
    vid = _ask("  video ID: ")
    if not vid:
        print("  batal.")
        return
    from .cli import main as cli_main

    cli_main(["analyze", "--video", vid, "--lang", lang])
    _pause()


def _act_search(config_dir: str) -> None:
    q = _ask("  query (mis: cegukan OR hiccup): ")
    if not q:
        print("  batal.")
        return
    from .cli import main as cli_main

    cli_main(["search", "--query", q])
    _pause()


def _act_cache(config_dir: str) -> None:
    from .cli import main as cli_main

    print("  1. stats   2. purge semua   3. gc")
    c = _ask("  pilihan: ")
    if c == "1":
        cli_main(["cache", "stats"])
    elif c == "2":
        if _ask("  Yakin hapus SEMUA cache? (y/N): ").lower() in ("y", "ya"):
            cli_main(["cache", "purge", "--all"])
        else:
            print("  batal.")
    elif c == "3":
        cli_main(["cache", "gc"])
    _pause()


def _act_blocked(config_dir: str) -> None:
    base = Path(config_dir)
    logs = sorted(base.glob("*_blocked.json")) if base.is_dir() else []
    if not logs:
        print("  tak ada log blocked.")
        _pause()
        return
    print("  Log blocked:")
    for i, f in enumerate(logs[:12], 1):
        print(f"   {i}. {f.name}")
    ch = _ask("  nomor (Enter=kembali): ")
    if ch.isdigit() and 1 <= int(ch) <= min(len(logs), 12):
        sel = logs[int(ch) - 1]
        print(f"  scan ulang dari log: {sel.name}")
        _run_engine("cs20_engine.py", [
            "--channel", sel.name.replace("_blocked.json", ""),
            "--retry-blocked-log", str(sel),
            "--config-dir", config_dir,
            "--checkpoint-dir", str(base / "checkpoints"),
            "--executor", "menu",
            "--webhook-url", os.environ.get("CS_WEBHOOK", ""),
        ])
    _pause()


def _act_passthrough(script: str, extra: list, config_dir: str) -> None:
    """Delegasi ke engine lama (interaktif internal) — tetap butuh input mereka."""
    args = ["--config-dir", config_dir, *extra]
    _run_engine(script, args)
    _pause()


# ---------------------------------------------------------------------------
# loop menu
# ---------------------------------------------------------------------------
def _pick_language() -> str:
    print("\n  BAHASA:")
    for k, (code, label) in _LANGS.items():
        print(f"   {k}. {label} ({code})")
    c = _ask("  pilih (Enter=Indonesia): ")
    return _LANGS.get(c, ("id", ""))[0]


def run_menu(config_dir: str = ".cs20", lang: str = "") -> int:
    _clear()
    print(_line())
    print("   CEGUKAN SEEKER - MENU (cs_core)")
    print(_line())

    try:
        if not lang:
            lang = _pick_language()
        print(f"\n  bahasa aktif: {lang}")

        while True:
            print()
            print(_line())
            print("   MENU")
            print(_line())
            print("   1. Scan channel        (pilih channel tersimpan / ketik)")
            print("   2. Analyze video       (ketik video ID)")
            print("   3. Search index        (query)")
            print("   4. Cache               (stats / purge / gc)")
            print("   5. Log blocked video")
            print("   6. Index Mode          (delegasi: batch channel besar)")
            print("   7. Recovery Age        (delegasi: bypass age-restricted)")
            print("   8. ChatSeeker          (delegasi: live-chat)")
            print("   9. Auto Drive          (delegasi: discovery channel)")
            print(f"   L. Ganti bahasa        (kini: {lang})")
            print("   0. Keluar")
            print(_line())

            choice = _ask("  pilihan: ").upper()
            if choice == "0":
                print("\n  sampai jumpa.")
                return 0
            elif choice == "1":
                _act_scan(lang, config_dir)
            elif choice == "2":
                _act_analyze(lang, config_dir)
            elif choice == "3":
                _act_search(config_dir)
            elif choice == "4":
                _act_cache(config_dir)
            elif choice == "5":
                _act_blocked(config_dir)
            elif choice == "6":
                _act_passthrough("cs20_index_engine.py", ["--lang", lang], config_dir)
            elif choice == "7":
                _act_passthrough("cs20_age_engine.py", ["--lang", lang], config_dir)
            elif choice == "8":
                _run_engine("chatseeker.py", [])
                _pause()
            elif choice == "9":
                _act_passthrough("cs20_autodrive_engine.py", [], config_dir)
            elif choice == "L":
                lang = _pick_language()
            else:
                print("  pilihan tak valid.")
    except _MenuExit:
        print("\n  (input berakhir) keluar dari menu.")
        return 0
