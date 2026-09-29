"""Menu interaktif `cs21` — entry utama (tanpa subcommand).

Dirancang untuk Termux/Android:

- pemilih panah + filter lewat `prompt_toolkit`; otomatis turun ke mode angka
  kalau paket tidak ada atau stdout bukan TTY;
- semua path dari lokasi repo (bukan CWD) sehingga bisa dijalankan dari mana pun;
- tidak pernah traceback: error engine ditangkap dan ditampilkan satu baris;
- Ctrl+C/EOF keluar bersih (checkpoint engine tetap tersimpan sendiri).

Aksi delegasi (Index/Age/AutoDrive/ChatSeeker) memanggil engine lama dengan
**argumen lengkap**, bukan mengandalkan prompt internal mereka.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import settings as _settings
from . import termux as _termux
from .errors import ExitCode
from .tui import ExitMenu, Option, UI

__all__ = ["run_menu", "load_saved_channels", "remember_channel"]

_REPO_ROOT = _settings.repo_root()

_LANGS = [
    Option("1", "Indonesia", "id"),
    Option("2", "English", "en"),
    Option("3", "Jepang", "jp"),
    Option("4", "Korea", "kr"),
    Option("5", "Hindi/India", "in"),
    Option("6", "Thailand", "th"),
]
_LANG_CODE = {"1": "id", "2": "en", "3": "jp", "4": "kr", "5": "in", "6": "th"}

_ENGINES = {
    "scan": "cs20_engine.py",
    "index": "cs20_index_engine.py",
    "age": "cs20_age_engine.py",
    "autodrive": "cs20_autodrive_engine.py",
    "chatseeker": "chatseeker.py",
}

# ---------------------------------------------------------------------------
# konteks sesi
# ---------------------------------------------------------------------------
@dataclass
class Ctx:
    ui: UI
    config_dir: Path
    lang: str
    settings: _settings.Settings
    executor: str = "Operator"

    @property
    def checkpoint_dir(self) -> Path:
        return self.config_dir / "checkpoints"

    def save_settings(self, **kw) -> None:
        self.settings = self.settings.with_(**kw)
        _settings.save(self.settings, self.config_dir)

# ---------------------------------------------------------------------------
# channel tersimpan
# ---------------------------------------------------------------------------
def load_saved_channels(config_dir: str | os.PathLike = "") -> list[str]:
    """Gabung channel dari channels.txt + checkpoint + index_cache (dedup, urut)."""
    base = Path(config_dir) if config_dir else _settings.config_dir()
    seen: list[str] = []
    seen_set: set[str] = set()

    def _add(name: str) -> None:
        name = (name or "").strip().lstrip("@")
        if name and name not in seen_set:
            seen_set.add(name)
            seen.append(name)

    candidates = [base]
    if base != _REPO_ROOT / ".cs20":
        candidates.append(_REPO_ROOT / ".cs20")

    for folder in candidates:
        f = folder / "channels.txt"
        if f.is_file():
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    _add(line)
            except OSError:
                pass

    for folder in candidates:
        cp_dir = folder / "checkpoints"
        if cp_dir.is_dir():
            try:
                for f in sorted(cp_dir.glob("*.checkpoint")):
                    _add(f.stem)
            except OSError:
                pass

    for root in (Path.home() / ".cs20" / "index_cache",
                 Path.home() / "storage" / "shared" / "CS20_Index"):
        try:
            if root.is_dir():
                for d in sorted(root.iterdir()):
                    if d.is_dir() and (d / "meta.json").is_file():
                        _add(d.name)
        except OSError:
            pass

    return seen

def remember_channel(channel: str, config_dir: str | os.PathLike = "") -> None:
    """Simpan channel ke channels.txt supaya lain kali tinggal dipilih."""
    channel = (channel or "").strip().lstrip("@")
    if not channel:
        return
    try:
        base = Path(config_dir) if config_dir else _settings.config_dir()
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

def _blocked_logs(config_dir: Path) -> list[Path]:
    try:
        return sorted(config_dir.glob("*_blocked.json"))
    except OSError:
        return []

def _blocked_count(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        videos = data.get("videos")
        if isinstance(videos, list):
            return len(videos)
    except (OSError, ValueError):
        pass
    return 0

def _index_root() -> Path:
    shared = Path.home() / "storage" / "shared" / "CS20_Index"
    try:
        if shared.parent.is_dir():
            return shared
    except OSError:
        pass
    return Path.home() / ".cs20" / "index_cache"

def _session_meta(channel: str) -> dict:
    path = _index_root() / channel / "meta.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

# ---------------------------------------------------------------------------
# pemilih channel
# ---------------------------------------------------------------------------
def _pick_channel(ctx: Ctx, *, prompt: str = "pilih channel",
                  allow_new: bool = True, preferred: str = "") -> str:
    saved = load_saved_channels(ctx.config_dir)
    if preferred and preferred in saved:
        saved = [preferred] + [c for c in saved if c != preferred]

    options = [Option(str(i), ch) for i, ch in enumerate(saved, 1)]
    if allow_new:
        options.append(Option("0", "➕ Channel baru", "ketik handle / UCxxx"))
    if not options:
        return _ask_new_channel(ctx)

    picked = ctx.ui.select(prompt, options, filterable=True)
    if picked is None:
        return ""
    if picked == "0":
        return _ask_new_channel(ctx)
    try:
        return saved[int(picked) - 1]
    except (ValueError, IndexError):
        return ""

def _ask_new_channel(ctx: Ctx) -> str:
    raw = ctx.ui.ask("channel (handle / UCxxx / URL)",
                     validate=_validate_channel)
    return _normalize_channel(raw)

def _normalize_channel(raw: str) -> str:
    """Buang '@', spasi, path, dan URL YouTube yang tidak diperlukan."""
    try:
        from .engine_compat import normalize_channel as _norm

        return _norm(raw)
    except ImportError:  # pragma: no cover - jalur paket selalu tersedia
        return (raw or "").strip().strip("@").replace(" ", "").rstrip("/")

def _validate_channel(value: str) -> str | None:
    text = _normalize_channel(value)
    if not text:
        return "channel tidak boleh kosong"
    if len(text) < 2:
        return "channel terlalu pendek"
    if " " in text:
        return "channel tidak boleh mengandung spasi"
    return None

# ---------------------------------------------------------------------------
# engine runner
# ---------------------------------------------------------------------------
def _engine_path(name: str) -> Path:
    return _REPO_ROOT / _ENGINES.get(name, name)

def _run_engine(ctx: Ctx, name: str, args: list[str], *, label: str = "",
                notify: bool = True, python_engine: str | None = None) -> int:
    """Jalankan engine lama; kembalikan exit code. Tidak pernah melempar."""
    if python_engine is None:
        script = _engine_path(name)
    else:
        script = _REPO_ROOT / python_engine
    if not script.is_file():
        ctx.ui.err(f"engine tidak ditemukan: {script.name}")
        ctx.ui.info("pastikan cs21 dijalankan dari folder repo CS21")
        return int(ExitCode.DEPENDENCY)

    cmd = [sys.executable, str(script), *args]
    ctx.ui.info(f"menjalankan: {script.name} {' '.join(args[:6])}{' …' if len(args) > 6 else ''}")
    locked = _termux.wake_lock() if ctx.settings.wake_lock else False
    try:
        rc = subprocess.call(cmd, cwd=str(_REPO_ROOT))
    except KeyboardInterrupt:
        ctx.ui.warn("dihentikan (checkpoint engine tetap tersimpan)")
        rc = int(ExitCode.INTERRUPTED)
    except OSError as exc:
        ctx.ui.err(f"gagal menjalankan {script.name}: {exc}")
        rc = int(ExitCode.FAIL)
    finally:
        if locked:
            _termux.wake_unlock()

    if rc == 0:
        ctx.ui.ok(f"{label or script.stem} selesai")
    else:
        ctx.ui.err(f"{label or script.stem} berhenti dengan kode {rc}")

    if notify and ctx.settings.notify:
        _termux.notify(
            "CS21 selesai" if rc == 0 else "CS21 berhenti",
            f"{label or script.stem} — exit {rc}",
            vibrate=rc == 0,
        )
    return rc

def _webhook_args(ctx: Ctx) -> list[str]:
    """Webhook dari file inject (`inject_webhook.sh`), sesuai bahasa aktif."""
    path = ctx.config_dir / ".webhook_injected"
    hooks: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            hooks[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    key = "WEBHOOK_INDONESIA" if ctx.lang == "id" else "WEBHOOK_GLOBAL"
    url = hooks.get(key) or os.environ.get("CS_WEBHOOK", "")
    return ["--webhook-url", url] if url else []

def _executor(ctx: Ctx) -> str:
    return ctx.executor or "Operator"

# ---------------------------------------------------------------------------
# aksi
# ---------------------------------------------------------------------------
def _act_scan(ctx: Ctx) -> None:
    channel = _pick_channel(ctx, prompt="scan channel", preferred=ctx.settings.last_channel)
    if not channel:
        ctx.ui.info("dibatalkan")
        return
    remember_channel(channel, ctx.config_dir)

    limit = ctx.ui.ask("berapa video terakhir (0 = semua)", default=str(ctx.settings.limit),
                       validate=_validate_int)
    live = ctx.ui.confirm("pakai dashboard Live?", default=ctx.ui.interactive)

    args = [
        "--channel", channel,
        "--limit", limit,
        "--jobs", str(ctx.settings.jobs),
        "--content-type", "all",
        "--executor", _executor(ctx),
        "--mode", "pantau" if live else "plain",
        "--config-dir", str(ctx.config_dir),
        "--checkpoint-dir", str(ctx.checkpoint_dir),
        "--lang", ctx.lang,
        *_webhook_args(ctx),
    ]
    ctx.save_settings(last_channel=channel, last_mode="scan", limit=int(limit or 20))
    _run_engine(ctx, "scan", args, label=f"scan @{channel}")

def _act_analyze(ctx: Ctx) -> None:
    raw = ctx.ui.ask("video ID atau URL", validate=lambda v: None if v.strip() else "wajib diisi")
    video_id = _video_id(raw)
    if not video_id:
        ctx.ui.err("ID video tidak valid (harus 11 karakter)")
        return

    from .cli import main as cli_main

    ctx.ui.info(f"menganalisa {video_id} ({ctx.lang})…")
    rc = cli_main(["analyze", "--video", video_id, "--lang", ctx.lang])
    if rc == 0 and ctx.ui.interactive:
        if _termux.have("termux-open-url"):
            if ctx.ui.confirm("buka video di YouTube?", default=False):
                _termux.open_url(f"https://www.youtube.com/watch?v={video_id}")
    elif rc != 0:
        ctx.ui.info("coba: cs21 doctor")

def _video_id(raw: str) -> str:
    text = (raw or "").strip()
    if "v=" in text:
        text = text.split("v=", 1)[1]
    text = text.split("&", 1)[0].split("?", 1)[0].strip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text if len(text) == 11 else ""

def _act_search(ctx: Ctx) -> None:
    query = ctx.ui.ask("kata kunci (mis: cegukan)", validate=lambda v: None if v.strip() else "wajib diisi")
    if not query:
        return
    from .cli import main as cli_main

    index_dir = str(_index_root())
    ctx.ui.info(f"cari di {index_dir}")
    cli_main(["search", "--query", query, "--index-dir", index_dir])

def _act_cache(ctx: Ctx) -> None:
    from .cli import main as cli_main

    picked = ctx.ui.select("kelola cache", [
        Option("1", "Statistik", "ukuran & jumlah file"),
        Option("2", "Bersihkan kedaluwarsa", "TTL 30 hari"),
        Option("3", "Hapus SEMUA cache", "tidak bisa dibatalkan"),
    ])
    if picked == "1":
        cli_main(["cache", "stats"])
    elif picked == "2":
        cli_main(["cache", "gc"])
    elif picked == "3":
        if ctx.ui.confirm("yakin hapus semua cache transcript?", default=False):
            cli_main(["cache", "purge", "--all"])
        else:
            ctx.ui.info("dibatalkan")

def _act_blocked(ctx: Ctx) -> None:
    logs = _blocked_logs(ctx.config_dir)
    if not logs:
        ctx.ui.info("belum ada log blocked video")
        return

    options = []
    for path in logs[:60]:
        channel = path.name.replace("_blocked.json", "")
        options.append(Option(channel, f"@{channel}", f"{_blocked_count(path)} video"))
    picked = ctx.ui.select("log blocked video", options, filterable=True)
    if not picked:
        return

    log_path = ctx.config_dir / f"{picked}_blocked.json"
    count = _blocked_count(log_path)
    ctx.ui.kv("channel", f"@{picked}")
    ctx.ui.kv("video", str(count))
    if not ctx.ui.confirm(f"scan ulang {count} video yang diblokir?", default=True):
        return

    args = [
        "--channel", picked,
        "--retry-blocked-log", str(log_path),
        "--config-dir", str(ctx.config_dir),
        "--checkpoint-dir", str(ctx.checkpoint_dir),
        "--executor", _executor(ctx),
        "--lang", ctx.lang,
        "--mode", "plain",
        "--jobs", str(ctx.settings.jobs),
        *_webhook_args(ctx),
    ]
    _run_engine(ctx, "scan", args, label=f"retry blocked @{picked}")

def _act_index(ctx: Ctx) -> None:
    channel = _pick_channel(ctx, prompt="index channel besar",
                            preferred=ctx.settings.last_channel)
    if not channel:
        ctx.ui.info("dibatalkan")
        return
    remember_channel(channel, ctx.config_dir)

    meta = _session_meta(channel)
    start_batch = 1
    total_videos = total_batches = batches_per_run = None

    if meta:
        batches = meta.get("batches") or []
        done = sum(1 for b in batches if isinstance(b, dict) and b.get("status") == "done")
        pending = next((b.get("batch_no") for b in batches
                        if isinstance(b, dict) and b.get("status") == "pending"), len(batches) + 1)
        ctx.ui.title(f"sesi index ditemukan: @{channel}")
        ctx.ui.kv("total video", str(meta.get("total_videos", "?")))
        ctx.ui.kv("batch", f"{done}/{len(batches)} selesai")
        ctx.ui.kv("dibuat", str(meta.get("created_at", "?")))

        choice = ctx.ui.select("lanjutkan sesi?", [
            Option("1", f"Lanjutkan dari batch {pending}"),
            Option("2", "Mulai sesi baru", "hapus cache sesi lama"),
            Option("3", "Batal"),
        ])
        if choice == "3" or choice is None:
            return
        if choice == "1":
            start_batch = int(pending or 1)
            total_videos = int(meta.get("total_videos") or 0)
            total_batches = int(meta.get("total_batches") or len(batches) or 10)
            batches_per_run = int(meta.get("batches_per_run") or 2)
        else:
            if not ctx.ui.confirm("hapus sesi lama?", default=False):
                return
            shutil.rmtree(_index_root() / channel, ignore_errors=True)
            ctx.ui.ok("sesi lama dihapus")

    if total_videos is None:
        ctx.ui.info("menghitung jumlah video (butuh beberapa detik)…")
        detected = _count_channel_videos(channel)
        default_videos = str(detected) if detected else "0"
        raw = ctx.ui.ask("total video", default=default_videos, validate=_validate_int)
        total_videos = int(raw or 0)
        if total_videos <= 0:
            ctx.ui.err("jumlah video harus > 0")
            return

        raw = ctx.ui.ask("jumlah batch", default="10", validate=_validate_int)
        total_batches = max(1, int(raw or 10))
        raw = ctx.ui.ask("batch per sesi", default="2", validate=_validate_int)
        batches_per_run = max(1, min(int(raw or 2), total_batches))
        jobs = ctx.ui.select("kecepatan", [
            Option("1", "Aman", "1 worker"),
            Option("2", "Seimbang", "2 worker"),
            Option("3", "Turbo", "3 worker"),
        ], default="2")
        jobs_n = {"1": 1, "2": 2, "3": 3}.get(jobs or "2", 2)
    else:
        jobs_n = ctx.settings.jobs

    per_batch = (total_videos + total_batches - 1) // max(1, total_batches)
    ctx.ui.title(f"ringkasan index @{channel}")
    ctx.ui.kv("video", str(total_videos))
    ctx.ui.kv("batch", f"{total_batches} × ~{per_batch} video")
    ctx.ui.kv("mulai dari", f"batch {start_batch}")
    ctx.ui.kv("jobs", str(jobs_n))
    if not ctx.ui.confirm("mulai index mode?", default=True):
        return

    args = [
        "--channel", channel,
        "--content-type", "video",
        "--executor", _executor(ctx),
        "--lang", ctx.lang,
        "--config-dir", str(ctx.config_dir),
        "--jobs", str(jobs_n),
        "--total-videos", str(total_videos),
        "--total-batches", str(total_batches),
        "--batches-per-run", str(batches_per_run),
        "--start-batch", str(start_batch),
        "--no-prompt",
        *_webhook_args(ctx),
    ]
    _run_engine(ctx, "index", args, label=f"index @{channel}")

def _count_channel_videos(channel: str) -> int:
    """Ambil playlist_count channel via yt-dlp (0 bila gagal)."""
    if not shutil.which("yt-dlp"):
        return 0
    url = f"https://www.youtube.com/@{channel}/videos"
    try:
        proc = subprocess.run(
            ["yt-dlp", "--playlist-items", "0", "--print", "playlist_count",
             "--quiet", "--no-warnings", "--socket-timeout", "15", url],
            capture_output=True, text=True, timeout=40,
        )
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return 0

def _act_age(ctx: Ctx) -> None:
    logs = _blocked_logs(ctx.config_dir)
    options = [Option("_new", "➕ Channel baru", "ketik handle")]
    for path in logs[:40]:
        options.append(Option(path.name.replace("_blocked.json", ""),
                              f"@{path.name.replace('_blocked.json', '')}",
                              "punya log blocked"))
    picked = ctx.ui.select("recovery age-restricted", options, filterable=True)
    if not picked:
        return
    channel = _ask_new_channel(ctx) if picked == "_new" else picked
    if not channel:
        return
    remember_channel(channel, ctx.config_dir)

    content = ctx.ui.select("tipe konten", [
        Option("1", "Semua", "live + video"),
        Option("2", "Video", "video biasa"),
        Option("3", "Live", "siaran langsung"),
    ], default="1")
    content_map = {"1": "all", "2": "video", "3": "live"}
    limit = ctx.ui.ask("jumlah video", default=str(ctx.settings.limit), validate=_validate_int)

    if not _cookies_ready(ctx):
        return

    args = [
        "--channel", channel,
        "--lang", ctx.lang,
        "--executor", _executor(ctx),
        "--config-dir", str(ctx.config_dir),
        "--content-type", content_map.get(content or "1", "all"),
        "--limit", limit,
        "--jobs", str(min(ctx.settings.jobs, 3)),
        "--no-prompt",
        *_webhook_args(ctx),
    ]
    _run_engine(ctx, "age", args, label=f"recovery age @{channel}")

def _cookies_ready(ctx: Ctx) -> bool:
    path = Path(os.environ.get("CS_COOKIES") or (ctx.config_dir / "cookies.txt"))
    if path.is_file() and path.stat().st_size > 0:
        ctx.ui.ok(f"cookies siap ({path.name})")
        return True
    ctx.ui.warn("cookies belum ada — video age-restricted kemungkinan gagal")
    ctx.ui.info("jalankan di terminal lain: bash setup_cookies.sh")
    return ctx.ui.confirm("lanjut tanpa cookies?", default=False)

def _act_autodrive(ctx: Ctx) -> None:
    ctx.ui.info("discovery channel baru otomatis (search + scan)")
    time_range = ctx.ui.select("rentang waktu upload", [
        Option("1", "Semua waktu", "all"),
        Option("2", "24 jam terakhir", "1d"),
        Option("3", "7 hari terakhir", "7d"),
        Option("4", "1 bulan terakhir", "1m"),
        Option("5", "1 tahun terakhir", "1y"),
    ], default="1")
    range_map = {"1": "all", "2": "1d", "3": "7d", "4": "1m", "5": "1y"}

    limit = ctx.ui.ask("video per channel baru", default="10", validate=_validate_int)
    cycles = ctx.ui.ask("maksimal siklus (0 = tanpa batas)", default="0", validate=_validate_int)
    query = ctx.ui.ask("query kustom (Enter = pakai bawaan)", default="")

    args = [
        "--lang", ctx.lang,
        "--time-range", range_map.get(time_range or "1", "all"),
        "--limit-per-channel", limit,
        "--max-cycles", cycles,
        "--config-dir", str(ctx.config_dir),
        "--checkpoint-dir", str(ctx.checkpoint_dir),
        "--executor", "autodrive",
        *_webhook_args(ctx),
    ]
    if query:
        args += ["--custom-query", query]
    _run_engine(ctx, "autodrive", args, label="auto drive")

def _act_chatseeker(ctx: Ctx) -> None:
    if not ctx.ui.interactive:
        ctx.ui.warn("ChatSeeker butuh terminal interaktif (tidak bisa dari pipe)")
        return
    if not _module_ok("rich"):
        ctx.ui.err("ChatSeeker butuh paket 'rich'")
        ctx.ui.info("pip install rich --break-system-packages")
        return
    _run_engine(ctx, "chatseeker", [], label="chatseeker")

def _act_doctor(ctx: Ctx) -> None:
    from .doctor import run_doctor

    run_doctor(fix=ctx.ui.interactive)

def _act_settings(ctx: Ctx) -> None:
    while True:
        s = ctx.settings
        ctx.ui.title("setelan")
        ctx.ui.kv("bahasa", s.lang)
        ctx.ui.kv("fuzzy", s.fuzzy)
        ctx.ui.kv("jobs", str(s.jobs))
        ctx.ui.kv("limit", str(s.limit))
        ctx.ui.kv("notifikasi", "aktif" if s.notify else "mati")
        ctx.ui.kv("wake-lock", "aktif" if s.wake_lock else "mati")

        picked = ctx.ui.select("ubah setelan", [
            Option("1", "Bahasa", s.lang),
            Option("2", "Fuzzy matching", s.fuzzy),
            Option("3", "Worker (jobs)", str(s.jobs)),
            Option("4", "Limit video", str(s.limit)),
            Option("5", "Notifikasi", "aktif" if s.notify else "mati"),
            Option("6", "Wake-lock", "aktif" if s.wake_lock else "mati"),
            Option("7", "Kembali"),
        ])
        if picked in (None, "7"):
            return
        if picked == "1":
            lang = _pick_language(ctx.ui, current=s.lang)
            ctx.save_settings(lang=lang)
        elif picked == "2":
            mode = ctx.ui.select("fuzzy matching", [
                Option("auto", "Otomatis", "on hanya kalau rapidfuzz native"),
                Option("on", "Selalu aktif", "deteksi typo ASR maksimal"),
                Option("off", "Mati", "paling cepat"),
            ], default=s.fuzzy)
            if mode:
                ctx.save_settings(fuzzy=mode)
        elif picked == "3":
            raw = ctx.ui.ask("jumlah worker (1-16)", default=str(s.jobs), validate=_validate_int)
            ctx.save_settings(jobs=max(1, min(int(raw or s.jobs), 16)))
        elif picked == "4":
            raw = ctx.ui.ask("limit video default", default=str(s.limit), validate=_validate_int)
            ctx.save_settings(limit=max(0, int(raw or s.limit)))
        elif picked == "5":
            ctx.save_settings(notify=not s.notify)
        elif picked == "6":
            ctx.save_settings(wake_lock=not s.wake_lock)

def _module_ok(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

def _validate_int(value: str) -> str | None:
    if value.strip() == "":
        return None
    return None if value.strip().lstrip("-").isdigit() else "harus berupa angka"

# ---------------------------------------------------------------------------
# helper tampilan
# ---------------------------------------------------------------------------
def _clear() -> None:
    """Dibersihkan hanya kalau TTY (dipakai juga oleh test)."""
    if not sys.stdout.isatty():
        return
    try:
        print("\033[2J\033[H", end="")
    except Exception:
        pass

def _pick_language(ui: UI, *, current: str = "") -> str:
    default = next((k for k, code in _LANG_CODE.items() if code == current), "")
    picked = ui.select("bahasa", _LANGS, default=default or "1")
    return _LANG_CODE.get(picked or "1", "id")

def _banner(ctx: Ctx) -> None:
    ui = ctx.ui
    ui.clear()
    ui.title("CS21 · Cegukan Seeker V21")
    status = [
        f"operator: {ctx.executor}",
        f"lang: {ctx.lang}",
        f"fuzzy: {_fuzzy_state(ctx)}",
        f"jobs: {ctx.settings.jobs}",
    ]
    ui.kv("", "  ".join(status), key_width=0)
    if not ui.interactive:
        ui.warn("mode non-interaktif (pipe) — beberapa aksi butuh terminal")
    missing = [name for name in _ENGINES.values() if not (_REPO_ROOT / name).is_file()]
    if missing:
        ui.warn(f"engine hilang: {', '.join(missing)}")

def _fuzzy_state(ctx: Ctx) -> str:
    """Mode fuzzy efektif: `auto` -> `on` hanya bila rapidfuzz native."""
    from . import config as _cfg

    effective = _cfg.fuzzy_mode(ctx.settings.fuzzy)
    if ctx.settings.fuzzy == "auto" and effective == "off":
        return "off (cepat)"
    return effective

def _apply_env(ctx: Ctx) -> None:
    """Terapkan setelan ke env proses (dipakai scoring & engine anak)."""
    from . import config as _cfg

    _cfg.apply_fuzzy_mode(ctx.settings.fuzzy)
    os.environ.setdefault("CS_CONFIG_DIR", str(ctx.config_dir))

def _menu_options(ctx: Ctx) -> list[Option]:
    blocked = len(_blocked_logs(ctx.config_dir))
    saved = len(load_saved_channels(ctx.config_dir))
    return [
        Option("1", "⚡ Scan channel", f"{saved} channel tersimpan"),
        Option("2", "🎬 Analisa video", "ID / URL YouTube"),
        Option("3", "🔎 Cari di index", "hasil mode Index"),
        Option("4", "📋 Log blocked", f"{blocked} log"),
        Option("5", "📦 Index Mode", "channel besar, batch"),
        Option("6", "🔞 Recovery Age", "video age-restricted"),
        Option("7", "💬 ChatSeeker", "live-chat VTuber"),
        Option("8", "🚗 Auto Drive", "discovery channel"),
        Option("9", "🧹 Cache", "stats / bersihkan"),
        Option("d", "🩺 Doctor", "cek & perbaiki dependensi"),
        Option("l", "🌐 Ganti bahasa", ctx.lang),
        Option("s", "⚙️  Setelan", f"jobs={ctx.settings.jobs} fuzzy={ctx.settings.fuzzy}"),
        Option("0", "Keluar"),
    ]

_ACTIONS = {
    "1": _act_scan,
    "2": _act_analyze,
    "3": _act_search,
    "4": _act_blocked,
    "5": _act_index,
    "6": _act_age,
    "7": _act_chatseeker,
    "8": _act_autodrive,
    "9": _act_cache,
    "d": _act_doctor,
}

# ---------------------------------------------------------------------------
# loop
# ---------------------------------------------------------------------------
def run_menu(config_dir: str | os.PathLike = "", lang: str = "") -> int:
    """Menu utama. Return exit code (0 normal, 130 Ctrl+C)."""
    settings = _settings.load(config_dir or None)
    cfg = _settings.config_dir(config_dir or None)
    ui = UI(mode=settings.ui)

    if not lang:
        lang = settings.lang
    if lang and lang not in set(_LANG_CODE.values()):
        lang = "id"

    executor = _read_executor(cfg)
    ctx = Ctx(ui=ui, config_dir=cfg, lang=lang, settings=settings.with_(lang=lang),
              executor=executor)
    _apply_env(ctx)
    ui.load_history(cfg / "history")

    try:
        if ui.interactive:
            _banner(ctx)
            if not ctx.settings.last_mode:
                lang = _pick_language(ui, current=ctx.lang)
                ctx.save_settings(lang=lang)
                ctx.lang = lang
                _apply_env(ctx)

        while True:
            _banner(ctx) if ui.interactive else None
            if not ui.interactive:
                _print_plain_menu(ctx)

            picked = ui.select("pilih menu", _menu_options(ctx), allow_cancel=False,
                               filterable=False)
            key = (picked or "").lower()

            if key in ("0", "q", "keluar", "exit"):
                print("\n  sampai jumpa.")
                return int(ExitCode.OK)

            if key == "l":
                ctx.lang = _pick_language(ui, current=ctx.lang)
                ctx.save_settings(lang=ctx.lang)
                _apply_env(ctx)
                ui.ok(f"bahasa: {ctx.lang}")
                continue

            if key == "s":
                _act_settings(ctx)
                _apply_env(ctx)
                continue

            action = _ACTIONS.get(key)
            if not action:
                print("  pilihan tak valid.")
                continue

            try:
                action(ctx)
            except ExitMenu:
                raise
            except KeyboardInterrupt:
                ui.warn("dihentikan — kembali ke menu")
            except Exception as exc:  # satu aksi gagal tidak boleh mematikan menu
                ui.err(f"{type(exc).__name__}: {exc}")
                ui.info("coba `d` (doctor) untuk cek lingkungan")

            if ui.interactive:
                try:
                    ui.pause()
                except ExitMenu:
                    raise
            ctx.save_settings(last_mode=key)

    except ExitMenu:
        print("\n  (input berakhir) keluar dari menu.")
        return int(ExitCode.OK)
    except KeyboardInterrupt:
        print("\n  dihentikan oleh user.")
        return int(ExitCode.INTERRUPTED)
    finally:
        ui.save_history(cfg / "history")

def _print_plain_menu(ctx: Ctx) -> None:
    """Header untuk pipe/cron; daftar opsi dicetak oleh `UI.select`."""
    print("=" * 46)
    print("  CS21 · Cegukan Seeker V21")
    print(f"  operator={ctx.executor} lang={ctx.lang} fuzzy={_fuzzy_state(ctx)}")
    print("=" * 46)

def _read_executor(cfg: Path) -> str:
    """Nama operator dari `.cs20/profile` (dibuat cs20.sh) atau $USER."""
    try:
        text = (cfg / "profile").read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return os.environ.get("USER") or os.environ.get("LOGNAME") or "Operator"
