"""CLI `cs21` (dulu `python -m cs_core`).

Tanpa subcommand -> menu interaktif. Dengan subcommand -> mode skrip
(cron/pipe friendly), stdout bersih untuk `--json`.

Subcommand:
- ``menu``                       menu interaktif (default)
- ``analyze --video ID``         fetch transcript + scoring satu video
- ``scan --channel NAME``        scan channel via cs20_engine.py (plain default)
- ``search --query "..."``       cari di index JSON
- ``index`` / ``age``            delegasi ke engine lama (argumen diteruskan)
- ``cache purge|gc|stats``       kelola cache transcript
- ``doctor``                     preflight Termux + perbaikan otomatis

Kontrak error/exit code ada di `cs_core.errors`. Semua diagnostik manusia
masuk **stderr** saat `--json` aktif, supaya stdout selalu JSON murni.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from . import settings as _settings
from .errors import (
    CsError,
    DependencyError,
    ExitCode,
    UsageError,
    describe_transcript_error,
    resolve_lang,
)

__all__ = ["main", "build_parser"]

_REPO_ROOT = _settings.repo_root()

# ---------------------------------------------------------------------------
# util
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _json_stdout(active: bool):
    """Saat `--json`: apa pun yang ditulis ke stdout dialihkan ke stderr.

    Yield stdout asli supaya payload JSON tetap bisa ditulis murni.
    """
    if not active:
        yield sys.stdout
        return
    real = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield real
    finally:
        sys.stdout = real

def _fail(message: str, hint: str = "", code: ExitCode = ExitCode.FAIL) -> int:
    print(f"error: {message}", file=sys.stderr)
    if hint:
        print(f"saran: {hint}", file=sys.stderr)
    return int(code)

def _warn(message: str) -> None:
    print(f"peringatan: {message}", file=sys.stderr)

def _ensure_config_dir(path: str) -> None:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------
def _cmd_analyze(args) -> int:
    video_id = (args.video or "").strip()
    if not video_id:
        return _fail("--video wajib diisi", "contoh: cs21 analyze --video gAQIEyzUHYc", ExitCode.USAGE)
    lang = resolve_lang(args.lang)

    # Lazy: hanya jalur analyze yang menyentuh fetch + scoring.
    from .compat import to_legacy
    from .config import CompatMode
    from .languages import load as load_lang
    from .scoring import score_segments
    from .transcript import TranscriptError, get_segments

    with _json_stdout(args.json) as out:
        try:
            segments, source, cache_status = get_segments(
                video_id, lang, root=args.cache_dir or None,
                force_refresh=args.refresh,
            )
        except TranscriptError as exc:
            err = describe_transcript_error(exc, video_id)
            return _fail(err.message, err.hint, err.code)
        except ImportError as exc:
            return _fail(
                f"dependensi belum terpasang: {exc}",
                "jalankan: cs21 doctor --fix",
                ExitCode.DEPENDENCY,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # boundary terakhir: jangan pernah traceback ke user
            return _fail(
                f"fetch transkrip gagal: {type(exc).__name__}: {exc}",
                "jalankan: cs21 doctor",
                ExitCode.FAIL,
            )

        spec = load_lang(lang)
        result = score_segments(segments, spec, video_id=video_id, lang=lang)
        legacy = to_legacy(result, mode=CompatMode.IMPROVED, engine="E")

        payload = {
            "video_id": video_id,
            "lang": lang,
            "source": source,
            "cache": cache_status,
            "segments": len(segments),
            "status": legacy["status"],
            "kasta": legacy["kasta"],
            "kasta_label": legacy["kasta_label"],
            "score": legacy["score"],
            "persentase": legacy["persentase"],
            "cluster_count": legacy["cluster_count"],
            "maraton_mins": legacy["maraton_mins"],
            "is_valid": legacy["is_valid"],
            "tier_counts": legacy["tier_counts"],
            "hits": legacy["hits"],
        }

        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        else:
            _print_summary(payload)
    return int(ExitCode.OK)

def _print_summary(p: dict) -> None:
    tc = p["tier_counts"]
    print(f"video      : {p['video_id']}")
    print(f"lang       : {p['lang']}")
    print(f"transcript : {p['segments']} segmen ({p['source']}, cache={p['cache']})")
    print(f"status     : {p['status']}")
    print(f"kasta      : {p['kasta']}  ({p['persentase']}%, score {p['score']})")
    print(f"label      : {p['kasta_label']}")
    print(
        "tiers      : "
        f"CORE={tc.get('CORE', 0)} TYPO={tc.get('TYPO', 0)} "
        f"SILENT={tc.get('SILENT', 0)} CONTEXT={tc.get('CONTEXT', 0)} FP={tc.get('FP', 0)}"
    )
    if p["hits"]:
        print(f"hits       : {len(p['hits'])}")
        for h in p["hits"][:10]:
            print(f"  [{h['time']}] {h['text']}")
        if len(p["hits"]) > 10:
            print(f"  … +{len(p['hits']) - 10} lagi")

# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def _default_index_dir() -> str:
    try:
        from cs20_index_parser import detect_cache_root  # type: ignore

        return detect_cache_root()
    except Exception:
        shared = os.path.expanduser("~/storage/shared")
        if os.path.isdir(shared):
            return os.path.join(shared, "CS20_Index")
        return str(Path.home() / ".cs20" / "index_cache")

def _cmd_search(args) -> int:
    query = (args.query or "").strip()
    if not query:
        return _fail("--query wajib diisi", 'contoh: cs21 search --query "cegukan"', ExitCode.USAGE)

    # Lazy: parser menarik rich hanya saat search benar-benar dipakai.
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from cs20_index_parser import search_index_batch  # type: ignore
    except ImportError as exc:
        return _fail(f"gagal memuat parser index: {exc}", "jalankan: cs21 doctor --fix", ExitCode.DEPENDENCY)

    index_dir = args.index_dir or _default_index_dir()
    with _json_stdout(args.json) as out:
        if not index_dir or not os.path.isdir(index_dir):
            return _fail(
                f"index tidak ditemukan: {index_dir or '(kosong)'}",
                "jalankan mode Index dulu (menu 5), atau isi --index-dir",
            )
        try:
            results = search_index_batch(index_dir, query, args.channel or "")
        except Exception as exc:
            return _fail(f"pencarian gagal: {type(exc).__name__}: {exc}", "jalankan: cs21 doctor")

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2), file=out)
            return int(ExitCode.OK)

        if not results:
            print("(tak ada hasil)")
            return int(ExitCode.OK)
        print(f"{len(results)} video cocok untuk query: {query!r}")
        for r in results:
            print(f"  {r['video_id']}  {len(r['hits'])} hit  ({r['kasta_label']})")
    return int(ExitCode.OK)

# ---------------------------------------------------------------------------
# scan / index / age (subprocess ke engine lama)
# ---------------------------------------------------------------------------
def _run_engine(script_name: str, passthrough: list, *, quiet_stdout: bool = False) -> int:
    """Jalankan engine lama; kembalikan exit code-nya apa adanya.

    `quiet_stdout=True` mengalihkan stdout engine ke stderr supaya stdout
    pemanggil tetap bersih (dipakai `scan --json`).
    """
    script = _REPO_ROOT / script_name
    if not script.is_file():
        return _fail(
            f"engine tidak ditemukan: {script_name}",
            "pastikan kamu menjalankan cs21 dari folder repo CS21",
            ExitCode.DEPENDENCY,
        )
    cmd = [sys.executable, str(script), *passthrough]
    kwargs = {"cwd": str(_REPO_ROOT)}
    if quiet_stdout:
        kwargs["stdout"] = sys.stderr
    try:
        return subprocess.call(cmd, **kwargs)
    except KeyboardInterrupt:
        print("\ndihentikan oleh user.", file=sys.stderr)
        return int(ExitCode.INTERRUPTED)
    except OSError as exc:
        return _fail(f"gagal menjalankan {script_name}: {exc}", "jalankan: cs21 doctor")

def _cmd_scan(args) -> int:
    channel = (args.channel or "").strip().lstrip("@")
    if not channel:
        return _fail("--channel wajib diisi", "contoh: cs21 scan --channel windahbasudara", ExitCode.USAGE)
    lang = resolve_lang(args.lang)
    _ensure_config_dir(args.config_dir)

    mode = "pantau" if args.ui else "plain"
    passthrough = [
        "--channel", channel,
        "--limit", str(args.limit),
        "--jobs", str(args.jobs),
        "--content-type", args.content_type,
        "--executor", args.executor,
        "--mode", mode,
        "--start-from", str(args.start_from),
        "--checkpoint-dir", args.checkpoint_dir,
        "--config-dir", args.config_dir,
        "--lang", lang,
        "--webhook-url", args.webhook_url,
    ]
    if args.display_name:
        passthrough += ["--display-name", args.display_name]
    if args.retry_blocked_log:
        passthrough += ["--retry-blocked-log", args.retry_blocked_log]

    rc = _run_engine("cs20_engine.py", passthrough, quiet_stdout=args.json)
    if args.json:
        print(json.dumps({
            "channel": channel,
            "mode": mode,
            "limit": args.limit,
            "exit": rc,
            "ok": rc == 0,
        }, ensure_ascii=False, indent=2))
    if rc != 0:
        print(
            f"error: scan berhenti dengan kode {rc}"
            + (f" (channel: {channel})" if channel else ""),
            file=sys.stderr,
        )
        print("saran: cek nama channel, koneksi, lalu `cs21 doctor`", file=sys.stderr)
        return int(rc) if rc in (0, 1, 2, 3, 4, 130) else int(ExitCode.FAIL)
    return int(ExitCode.OK)

# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _cmd_cache(args) -> int:
    from . import cache as _cache

    root = args.cache_dir or None
    with _json_stdout(getattr(args, "json", False)) as out:
        if args.cache_cmd == "purge":
            n = _cache.purge(
                video_id=args.video,
                lang=args.lang,
                channel=args.channel,
                all=args.all,
                max_age_days=args.max_age,
                root=root,
            )
            print(f"purge: {n} file dihapus")
            return int(ExitCode.OK)
        if args.cache_cmd == "gc":
            n = _cache.gc(root=root, ttl_days=args.ttl_days)
            print(f"gc: {n} file kedaluwarsa dihapus")
            return int(ExitCode.OK)
        if args.cache_cmd == "stats":
            return _cache_stats(root, as_json=getattr(args, "json", False), out=out)
    return _fail("subcommand cache tidak dikenal", "pilih: purge | gc | stats", ExitCode.USAGE)

def _cache_stats(root, *, as_json: bool = False, out=None) -> int:
    from . import cache as _cache

    out = out or sys.stdout
    base = _cache.cache_root(root)
    files = list(base.glob("*.jsonl.gz"))
    total_bytes = 0
    for path in files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    if as_json:
        print(json.dumps({
            "dir": str(base),
            "files": len(files),
            "bytes": total_bytes,
            "human": _human_size(total_bytes),
        }, ensure_ascii=False, indent=2), file=out)
        return int(ExitCode.OK)
    print(f"cache dir : {base}")
    print(f"files     : {len(files)}")
    print(f"size      : {_human_size(total_bytes)}")
    return int(ExitCode.OK)

def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"

# ---------------------------------------------------------------------------
# menu
# ---------------------------------------------------------------------------
def _cmd_menu(args) -> int:
    from .menu import run_menu

    try:
        return run_menu(config_dir=args.config_dir, lang=args.lang or "")
    except KeyboardInterrupt:
        print()
        return int(ExitCode.INTERRUPTED)

# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cs21",
        description="Cegukan Seeker V21 — tanpa argumen = menu interaktif (ramah HP).",
    )
    parser.add_argument("--version", action="version", version=f"cs_core {__version__}")
    parser.add_argument("--config-dir", default="", dest="config_dir",
                        help="direktori config/checkpoint (default: <repo>/.cs20)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="tampilkan detail teknis saat error")
    sub = parser.add_subparsers(dest="command")

    p_menu = sub.add_parser("menu", help="menu interaktif (default tanpa argumen)")
    p_menu.add_argument("--lang", default="", help="lewati pemilihan bahasa")
    p_menu.set_defaults(func=_cmd_menu)

    p_analyze = sub.add_parser("analyze", help="fetch transcript + scoring satu video")
    p_analyze.add_argument("--video", required=True, help="YouTube video ID")
    p_analyze.add_argument("--lang", default="id", help="id/en/jp/kr/in/th")
    p_analyze.add_argument("--cache-dir", default="", help="root cache transcript")
    p_analyze.add_argument("--json", action="store_true", help="output JSON murni")
    p_analyze.add_argument("--refresh", action="store_true", help="paksa fetch ulang")
    p_analyze.set_defaults(func=_cmd_analyze)

    p_search = sub.add_parser("search", help="cari query di JSON index")
    p_search.add_argument("--query", required=True, help="query pencarian")
    p_search.add_argument("--index-dir", default="", help="direktori JSON index")
    p_search.add_argument("--channel", default="", help="label channel (opsional)")
    p_search.add_argument("--json", action="store_true", help="output JSON murni")
    p_search.set_defaults(func=_cmd_search)

    p_scan = sub.add_parser("scan", help="scan channel non-interaktif (plain default)")
    p_scan.add_argument("--channel", required=True, help="handle / channel_id / URL")
    p_scan.add_argument("--lang", default="id", help="id/en/jp/kr/in/th")
    p_scan.add_argument("--limit", type=int, default=50, help="jumlah video (<=0 = semua)")
    p_scan.add_argument("--jobs", type=int, default=4, help="worker paralel")
    p_scan.add_argument("--content-type", default="all", help="live | video | all",
                        dest="content_type")
    p_scan.add_argument("--executor", default="cli", help="nama operator di laporan")
    p_scan.add_argument("--start-from", type=int, default=0, dest="start_from")
    p_scan.add_argument("--checkpoint-dir", default="", dest="checkpoint_dir")
    p_scan.add_argument("--config-dir", default="", dest="config_dir")
    p_scan.add_argument("--webhook-url", default="", dest="webhook_url",
                        help="URL Discord; kosong = tanpa kirim laporan")
    p_scan.add_argument("--display-name", default="", dest="display_name")
    p_scan.add_argument("--retry-blocked-log", default="", dest="retry_blocked_log")
    p_scan.add_argument("--ui", action="store_true",
                        help="pakai dashboard Live (default: plain/cron-friendly)")
    p_scan.add_argument("--json", action="store_true", help="ringkas hasil sebagai JSON")
    p_scan.set_defaults(func=_cmd_scan)

    p_index = sub.add_parser("index", help="delegasi ke cs20_index_engine.py")
    p_index.add_argument("passthrough", nargs=argparse.REMAINDER)
    p_index.set_defaults(func=lambda a: _run_engine("cs20_index_engine.py", a.passthrough))

    p_age = sub.add_parser("age", help="delegasi ke cs20_age_engine.py")
    p_age.add_argument("passthrough", nargs=argparse.REMAINDER)
    p_age.set_defaults(func=lambda a: _run_engine("cs20_age_engine.py", a.passthrough))

    p_cache = sub.add_parser("cache", help="kelola cache transcript")
    p_cache.add_argument("--cache-dir", default="", help="root cache transcript")
    p_cache.add_argument("--json", action="store_true", help="output JSON murni (stats)")
    cache_sub = p_cache.add_subparsers(dest="cache_cmd", required=True)

    c_purge = cache_sub.add_parser("purge", help="hapus file cache")
    c_purge.add_argument("--video", default=None)
    c_purge.add_argument("--lang", default=None)
    c_purge.add_argument("--channel", default=None)
    c_purge.add_argument("--all", action="store_true")
    c_purge.add_argument("--max-age", type=int, default=None, dest="max_age")
    c_purge.set_defaults(func=_cmd_cache)

    c_gc = cache_sub.add_parser("gc", help="sapu cache kedaluwarsa")
    c_gc.add_argument("--ttl-days", type=int, default=None, dest="ttl_days")
    c_gc.set_defaults(func=_cmd_cache)

    c_stats = cache_sub.add_parser("stats", help="statistik cache")
    c_stats.add_argument("--json", action="store_true", help="output JSON murni")
    c_stats.set_defaults(func=_cmd_cache)

    p_doctor = sub.add_parser("doctor", help="preflight Termux: cek dependensi & perbaiki")
    p_doctor.add_argument("--fix", action="store_true", help="coba perbaiki otomatis")
    p_doctor.add_argument("--json", action="store_true", help="output JSON murni")
    p_doctor.set_defaults(func=_cmd_doctor)

    return parser

def _cmd_doctor(args) -> int:
    from .doctor import run_doctor

    return run_doctor(fix=args.fix, as_json=args.json)

# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------
def _normalize_paths(args) -> None:
    """Path default dari lokasi repo, bukan CWD (aman dipanggil dari mana pun)."""
    cfg = args.__dict__.get("config_dir") or ""
    if not cfg:
        cfg = str(_settings.config_dir())
        args.__dict__["config_dir"] = cfg
    if "checkpoint_dir" in args.__dict__ and not args.__dict__.get("checkpoint_dir"):
        args.__dict__["checkpoint_dir"] = str(Path(cfg) / "checkpoints")

def _apply_fuzzy_setting() -> None:
    """Terapkan preferensi fuzzy dari settings.json ke env proses.

    `CS_FUZZY_MODE` (env) menang atas settings; `CS_ENABLE_FUZZY` eksplisit
    menang atas keduanya (lihat `config.enable_fuzzy`).
    """
    from . import config as _cfg

    if os.environ.get(_cfg.FUZZY_MODE_ENV):
        _cfg.apply_fuzzy_mode()
        return
    _cfg.apply_fuzzy_mode(_settings.load().fuzzy)

def main(argv=None) -> int:
    # Console non-UTF8 (mis. Windows cp1252) tak bisa cetak emoji label kasta.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    argv_eff = list(sys.argv[1:]) if argv is None else list(argv)

    # `index`/`age` meneruskan SEMUA argumen ke engine lama. `argparse.REMAINDER`
    # tidak menangkap flag yang langsung menyusul subcommand, jadi diambil di
    # sini sebelum parser sempat menolaknya.
    if argv_eff and argv_eff[0] in ("index", "age") and not (
        {"-h", "--help"} & set(argv_eff)
    ):
        script = ("cs20_index_engine.py" if argv_eff[0] == "index"
                  else "cs20_age_engine.py")
        return _run_engine(script, argv_eff[1:])

    args = parser.parse_args(argv_eff)

    if not getattr(args, "func", None):
        # Tanpa subcommand -> menu interaktif (ramah HP/Android).
        args = parser.parse_args([*argv_eff, "menu"])

    _normalize_paths(args)
    _apply_fuzzy_setting()

    try:
        return int(args.func(args))
    except UsageError as exc:
        return _fail(exc.message, exc.hint, exc.code)
    except DependencyError as exc:
        return _fail(exc.message, exc.hint, exc.code)
    except CsError as exc:
        return _fail(exc.message, exc.hint, exc.code)
    except KeyboardInterrupt:
        print("\ndihentikan oleh user.", file=sys.stderr)
        return int(ExitCode.INTERRUPTED)
    except BrokenPipeError:
        return int(ExitCode.OK)

if __name__ == "__main__":
    raise SystemExit(main())
