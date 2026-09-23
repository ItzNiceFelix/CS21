"""CLI baru `python -m cs_core` (Fase 7 / T7.1).

Subcommand:
- `scan     --channel NAME [--limit N] [--lang id] [--ui]`
  scan channel non-interaktif (engine utama; plain default untuk cron).
- `analyze  --video ID [--lang id] [--cache-dir PATH] [--json]`
  fetch transcript (cs_core.transcript) -> scoring (cs_core.scoring) -> ringkas.
- `search   --query "..." [--index-dir PATH] [--channel NAME]`
  delegasi ke `cs20_index_parser.search_index_batch`.
- `index` / `age`  delegasi subprocess ke `cs20_index_engine.py` /
  `cs20_age_engine.py`; argumen diteruskan apa adanya setelah subcommand.
- `cache    purge|gc|stats`  lewat `cs_core.cache`.

Desain: TANPA `rich`, TANPA import berat di startup. `--help` dan subcommand
non-analyze tidak menyentuh youtube-transcript-api/requests. Import fungsi
yang butuh deps dilakukan DI DALAM handler (lazy).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__

__all__ = ["main", "build_parser"]

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------
def _cmd_analyze(args) -> int:
    # Lazy: hanya jalur analyze yang menyentuh fetch + scoring.
    from .compat import to_legacy
    from .config import CompatMode
    from .languages import load as load_lang
    from .scoring import score_segments
    from .transcript import TranscriptError, get_segments

    video_id = (args.video or "").strip()
    if not video_id:
        print("error: --video wajib diisi", file=sys.stderr)
        return 2
    lang = (args.lang or "id").strip() or "id"
    root = args.cache_dir or None

    # `--json`: engine lama boleh mencetak peringatan (mis. storage) ke stdout;
    # alihkan sementara ke stderr supaya stdout tetap JSON murni.
    real_stdout = sys.stdout
    if args.json:
        sys.stdout = sys.stderr
    try:
        try:
            segments, source, cache_status = get_segments(
                video_id, lang, root=root, force_refresh=args.refresh
            )
        except TranscriptError as exc:
            print(f"error: transcript gagal ({video_id}): {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # boundary: pesan ramah, detail ke stderr
            print(
                f"error: fetch transcript gagal: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

        spec = load_lang(lang)
        result = score_segments(segments, spec, video_id=video_id, lang=lang)
        legacy = to_legacy(result, mode=CompatMode.IMPROVED, engine="E")
    finally:
        sys.stdout = real_stdout

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
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    _print_summary(payload)
    return 0


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
def _cmd_search(args) -> int:
    query = (args.query or "").strip()
    if not query:
        print("error: --query wajib diisi", file=sys.stderr)
        return 2

    # Lazy: parser menarik rich/subprocess hanya saat search benar-benar dipakai.
    sys.path.insert(0, str(_REPO_ROOT))
    from cs20_index_parser import search_index_batch  # type: ignore

    index_dir = args.index_dir or _default_index_dir()
    if not index_dir or not os.path.isdir(index_dir):
        print(f"error: index-dir tidak ditemukan: {index_dir or '(kosong)'}", file=sys.stderr)
        return 1

    results = search_index_batch(index_dir, query, args.channel or "")
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if not results:
        print("(tak ada hasil)")
        return 0
    print(f"{len(results)} video cocok untuk query: {query!r}")
    for r in results:
        print(f"  {r['video_id']}  {len(r['hits'])} hit  ({r['kasta_label']})")
    return 0


def _default_index_dir() -> str:
    try:
        from cs20_index_parser import detect_cache_root  # type: ignore

        return detect_cache_root()
    except Exception:
        shared = os.path.expanduser("~/storage/shared")
        if os.path.isdir(shared):
            return os.path.join(shared, "CS20_Index")
        return os.path.expanduser("~/.cs20/index_cache")


# ---------------------------------------------------------------------------
# scan (non-interaktif, engine utama sebagai subprocess)
# ---------------------------------------------------------------------------
def _cmd_scan(args) -> int:
    """Scan channel via cs20_engine.py TANPA prompt.

    Semua opsi dari flag; default non-UI (plain) supaya aman untuk cron, pipe,
    atau stdout non-TTY. Pakai --ui untuk dashboard Live.
    """
    channel = (args.channel or "").strip()
    if not channel:
        print("error: --channel wajib diisi", file=sys.stderr)
        return 2

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
        "--lang", args.lang,
        "--webhook-url", args.webhook_url,
    ]
    if args.display_name:
        passthrough += ["--display-name", args.display_name]
    if args.retry_blocked_log:
        passthrough += ["--retry-blocked-log", args.retry_blocked_log]
    return _run_engine("cs20_engine.py", passthrough)


# ---------------------------------------------------------------------------
# index / age (subprocess passthrough)
# ---------------------------------------------------------------------------
def _run_engine(script_name: str, passthrough: list) -> int:
    script = _REPO_ROOT / script_name
    if not script.is_file():
        print(f"error: engine tidak ditemukan: {script}", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(script), *passthrough]
    return subprocess.call(cmd, cwd=str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _cmd_cache(args) -> int:
    from . import cache as _cache

    root = args.cache_dir or None
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
        return 0
    if args.cache_cmd == "gc":
        n = _cache.gc(root=root, ttl_days=args.ttl_days)
        print(f"gc: {n} file kedaluwarsa dihapus")
        return 0
    if args.cache_cmd == "stats":
        return _cache_stats(root)
    print("error: subcommand cache tidak dikenal", file=sys.stderr)
    return 2


def _cache_stats(root) -> int:
    from . import cache as _cache

    base = _cache.cache_root(root)
    files = list(base.glob("*.jsonl.gz"))
    total_bytes = 0
    for path in files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    print(f"cache dir : {base}")
    print(f"files     : {len(files)}")
    print(f"size      : {_human_size(total_bytes)}")
    return 0


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


# ---------------------------------------------------------------------------
# parser + entry
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cs_core",
        description="Cegukan Seeker core CLI (cs_core). "
                    "Tanpa argumen = menu interaktif (ramah HP).",
    )
    parser.add_argument("--version", action="version", version=f"cs_core {__version__}")
    parser.add_argument("--config-dir", default=".cs20", dest="config_dir",
                        help="direktori config/checkpoint (default .cs20)")
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="fetch transcript + scoring satu video")
    p_analyze.add_argument("--video", required=True, help="YouTube video ID")
    p_analyze.add_argument("--lang", default="id", help="kode bahasa (id/en/jp/kr/in/th)")
    p_analyze.add_argument("--cache-dir", default="", help="root cache transcript")
    p_analyze.add_argument("--json", action="store_true", help="output JSON")
    p_analyze.add_argument("--refresh", action="store_true", help="paksa fetch ulang")
    p_analyze.set_defaults(func=_cmd_analyze)

    p_search = sub.add_parser("search", help="cari query di JSON index")
    p_search.add_argument("--query", required=True, help="query pencarian")
    p_search.add_argument("--index-dir", default="", help="direktori JSON index")
    p_search.add_argument("--channel", default="", help="label channel (opsional)")
    p_search.add_argument("--json", action="store_true", help="output JSON")
    p_search.set_defaults(func=_cmd_search)

    p_scan = sub.add_parser(
        "scan",
        help="scan channel non-interaktif (engine utama, plain default)",
    )
    p_scan.add_argument("--channel", required=True, help="handle / channel_id / URL")
    p_scan.add_argument("--lang", default="id", help="kode bahasa (id/en/jp/kr/in/th)")
    p_scan.add_argument("--limit", type=int, default=50, help="jumlah video (<=0 = semua)")
    p_scan.add_argument("--jobs", type=int, default=4, help="worker paralel")
    p_scan.add_argument("--content-type", default="all", help="live | video | all",
                        dest="content_type")
    p_scan.add_argument("--executor", default="cli", help="nama operator di laporan")
    p_scan.add_argument("--start-from", type=int, default=0, dest="start_from")
    p_scan.add_argument("--checkpoint-dir", default=".cs20/checkpoints",
                        dest="checkpoint_dir")
    p_scan.add_argument("--config-dir", default=".cs20", dest="config_dir")
    p_scan.add_argument("--webhook-url", default="", dest="webhook_url",
                        help="URL Discord; kosong = tanpa kirim laporan")
    p_scan.add_argument("--display-name", default="", dest="display_name")
    p_scan.add_argument("--retry-blocked-log", default="", dest="retry_blocked_log")
    p_scan.add_argument("--ui", action="store_true",
                        help="pakai dashboard Live (default: plain/cron-friendly)")
    p_scan.set_defaults(func=_cmd_scan)

    p_index = sub.add_parser("index", help="delegasi ke cs20_index_engine.py")
    p_index.add_argument("passthrough", nargs=argparse.REMAINDER)
    p_index.set_defaults(
        func=lambda a: _run_engine("cs20_index_engine.py", a.passthrough)
    )

    p_age = sub.add_parser("age", help="delegasi ke cs20_age_engine.py")
    p_age.add_argument("passthrough", nargs=argparse.REMAINDER)
    p_age.set_defaults(func=lambda a: _run_engine("cs20_age_engine.py", a.passthrough))

    p_cache = sub.add_parser("cache", help="kelola cache transcript")
    p_cache.add_argument("--cache-dir", default="", help="root cache transcript")
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
    c_stats.set_defaults(func=_cmd_cache)

    return parser


def main(argv=None) -> int:
    # Console non-UTF8 (mis. Windows cp1252) tak bisa cetak emoji label kasta.
    # Reconfigure aman di Termux; ganti char yang tak terwakili.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # Tanpa subcommand -> menu interaktif (ramah HP/Android).
        from .menu import run_menu
        try:
            return run_menu(config_dir=args.__dict__.get("config_dir", ".cs20"))
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
