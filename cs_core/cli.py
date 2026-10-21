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
import shutil
import subprocess
import sys
import time as _time
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
from .video import parse_video_id, video_url

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
    raw_inputs = _collect_video_inputs(args)
    if not raw_inputs:
        return _fail("--video wajib diisi", "contoh: cs21 analyze --video gAQIEyzUHYc", ExitCode.USAGE)

    lang = resolve_lang(args.lang)
    video_ids: list[str] = []
    for raw in raw_inputs:
        vid = parse_video_id(raw)
        if not vid:
            return _fail(
                f"ID video tidak valid: {raw!r}",
                "tempel URL YouTube (youtu.be/…, watch?v=…) atau ID 11 karakter",
                ExitCode.USAGE,
            )
        if vid not in video_ids:
            video_ids.append(vid)

    payloads: list[dict] = []
    failures: list[tuple[str, CsError]] = []

    with _json_stdout(args.json) as out:
        for index, video_id in enumerate(video_ids, 1):
            if not args.json and len(video_ids) > 1:
                print(f"[{index}/{len(video_ids)}] {video_id}", file=sys.stderr)
            try:
                payloads.append(_analyze_one(video_id, lang, args))
            except CsError as exc:
                failures.append((video_id, exc))
                if len(video_ids) == 1:
                    return _fail(exc.message, exc.hint, exc.code)
                print(f"  gagal: {exc.message}", file=sys.stderr)

        if not payloads:
            first = failures[0][1] if failures else None
            if first is not None:
                return _fail(first.message, first.hint, first.code)
            return int(ExitCode.FAIL)

        report_file = None
        if args.html:
            report_file = _write_video_report(payloads, lang, args)

        if args.json:
            # Bentuk payload mengikuti jumlah video yang DIMINTA, bukan yang
            # berhasil: satu video -> objek, banyak -> array. Tanpa ini,
            # kegagalan sebagian mengubah tipe JSON dan memecah konsumen.
            body = payloads[0] if len(video_ids) == 1 else payloads
            if report_file is not None:
                body = {"results": body, "report": str(report_file)}
            print(json.dumps(body, ensure_ascii=False, indent=2), file=out)
        else:
            for i, payload in enumerate(payloads):
                if i:
                    print()
                _print_summary(payload)
            if report_file is not None:
                print(f"\nlaporan    : {report_file}")
            if failures:
                print(f"\n{len(failures)} video gagal dianalisa", file=sys.stderr)

    if args.open and report_file is not None:
        _open_report(report_file)
    return int(ExitCode.OK)

def _collect_video_inputs(args) -> list[str]:
    """Gabung `--video` (boleh berkoma), `--video` berulang, dan `--from-file`."""
    out: list[str] = []
    for value in getattr(args, "video", None) or []:
        for chunk in str(value).replace(",", "\n").splitlines():
            chunk = chunk.strip()
            if chunk and not chunk.startswith("#"):
                out.append(chunk)
    path = getattr(args, "from_file", "") or ""
    if path:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise UsageError(f"tidak bisa membaca {path}: {exc}",
                             hint="pastikan path benar") from exc
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out

def _analyze_one(video_id: str, lang: str, args) -> dict:
    """Fetch + scoring satu video -> payload siap cetak."""
    # Lazy: hanya jalur analyze yang menyentuh fetch + scoring.
    from .compat import to_legacy
    from .config import CompatMode
    from .languages import load as load_lang
    from .scoring import score_segments
    from .transcript import TranscriptError, get_segments

    try:
        segments, source, cache_status = get_segments(
            video_id, lang, root=args.cache_dir or None,
            force_refresh=args.refresh,
        )
    except TranscriptError as exc:
        raise describe_transcript_error(exc, video_id) from exc
    except ImportError as exc:
        raise DependencyError(
            f"dependensi belum terpasang: {exc}",
            hint="jalankan: cs21 doctor --fix",
        ) from exc
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # boundary terakhir: jangan pernah traceback ke user
        raise CsError(
            f"fetch transkrip gagal: {type(exc).__name__}: {exc}",
            hint="jalankan: cs21 doctor",
        ) from exc

    spec = load_lang(lang)
    result = score_segments(segments, spec, video_id=video_id, lang=lang)
    legacy = to_legacy(result, mode=CompatMode.IMPROVED, engine="E")

    return {
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
        "similarity": legacy["mean_similarity"],
        "hits": legacy["hits"],
        "html_rows": legacy["html_rows"],
    }

def _write_video_report(payloads: list[dict], lang: str, args) -> Path:
    """Tulis satu laporan HTML untuk semua video yang baru dianalisa."""
    from .compat import to_legacy  # noqa: F401  (kontrak payload sudah legacy)
    from .report import build_html
    from . import reports as _reports

    results = []
    for payload in payloads:
        item = dict(payload)
        item.setdefault("status_label", payload.get("kasta_label", ""))
        results.append(item)

    label = payloads[0]["video_id"] if len(payloads) == 1 else f"{len(payloads)}video"
    html = build_html(
        channel=label,
        executor=args.executor or "Operator",
        results=results,
        lang=lang,
        meta={"display_name": ""},
    )
    path = _reports.report_path(label)
    path.write_text(html, encoding="utf-8")
    return path

def _open_report(path: Path) -> None:
    """Buka laporan di aplikasi Android (no-op bila Termux:API tidak ada)."""
    from . import termux as _termux

    if not _termux.open_file(path):
        print(f"catatan: buka manual -> {path}", file=sys.stderr)

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
    sim = p.get("similarity")
    if sim is not None:
        print(f"similarity : {sim * 100:.1f}% rata-rata kecocokan CORE")
    if p["hits"]:
        print(f"hits       : {len(p['hits'])}")
        for h in p["hits"][:10]:
            detail = ""
            hs = h.get("similarity") or {}
            if hs:
                best = max(hs.values())
                if best < 1.0:
                    detail = f"  (fuzzy {best * 100:.0f}%)"
            print(f"  [{h['time']}] {h['text']}{detail}")
        if len(p["hits"]) > 10:
            print(f"  … +{len(p['hits']) - 10} lagi")

# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def _default_index_dir() -> str:
    """Root index = root cache primer (tanpa impor parser/rich)."""
    from . import paths as _paths

    return str(_paths.primary_cache_root())

def _cmd_search(args) -> int:
    from .search import search as _search

    query = (args.query or "").strip()
    if not query:
        return _fail("--query wajib diisi", 'contoh: cs21 search --query "cegukan"', ExitCode.USAGE)

    explicit_index = bool(args.index_dir)
    if args.source is not None:
        sources = tuple(s for s in ("index", "cache") if s in set(args.source))
    elif explicit_index:
        # Path eksplisit = lingkup eksplisit: jangan campur cache di tempat lain.
        sources = ("index",)
    else:
        sources = ("index", "cache")
    index_root = args.index_dir or _default_index_dir()

    if "index" in sources and explicit_index and not os.path.isdir(index_root):
        return _fail(
            f"index tidak ditemukan: {index_root}",
            "jalankan mode Index dulu (menu 5), atau isi --index-dir yang benar",
        )

    with _json_stdout(args.json) as out:
        results = _search(
            query,
            index_root=index_root if "index" in sources else None,
            cache_root=args.cache_dir or None,
            channel=args.channel or "",
            sources=sources,
        )

        if args.json:
            print(json.dumps([_result_payload(r) for r in results],
                             ensure_ascii=False, indent=2), file=out)
            return int(ExitCode.OK)

        if not results:
            print(f"(tak ada hasil untuk {query!r})")
            if "index" in sources and not os.path.isdir(index_root):
                print(f"  catatan: folder index belum ada: {index_root}")
                print("  jalankan mode Index (menu 5) atau pakai --source cache")
            return int(ExitCode.OK)

        total = sum(r.hit_count for r in results)
        print(f"{len(results)} video, {total} momen cocok untuk {query!r}")
        rows = [
            (
                r.video_id,
                str(r.hit_count),
                r.hits[0].time if r.hits else "-",
                r.source,
                r.hits[0].text[:44] if r.hits else "",
            )
            for r in results
        ]
        _print_table(("VIDEO", "HIT", "AWAL", "SUMBER", "KUTIPAN"), rows)
    return int(ExitCode.OK)

def _result_payload(result) -> dict:
    return {
        "video_id": result.video_id,
        "source": result.source,
        "lang": result.lang,
        "channel": result.channel,
        "hits": [
            {"sec": int(h.sec), "time": h.time, "text": h.text, "url": h.url}
            for h in result.hits
        ],
    }

def _print_table(headers, rows) -> None:
    """Tabel teks rata kolom tanpa dependensi."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    print("  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print("  " + "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip())

# ---------------------------------------------------------------------------
# scan / index / age (subprocess ke engine lama)
# ---------------------------------------------------------------------------
def _run_engine(script_name: str, passthrough: list, *, quiet_stdout: bool = False,
                requires: tuple = ()) -> int:
    """Jalankan engine lama; kembalikan exit code-nya apa adanya.

    `quiet_stdout=True` mengalihkan stdout engine ke stderr supaya stdout
    pemanggil tetap bersih (dipakai `scan --json`).

    `requires` = dependensi yang harus ada SEBELUM engine jalan (`("yt-dlp",)`).
    Tanpa preflight, engine lama gagal jauh di tengah dengan pesan samar
    ("Tidak ada video ditemukan") padahal penyebabnya binary hilang.
    """
    script = _REPO_ROOT / script_name
    if not script.is_file():
        return _fail(
            f"engine tidak ditemukan: {script_name}",
            "pastikan kamu menjalankan cs21 dari folder repo CS21",
            ExitCode.DEPENDENCY,
        )
    missing = [name for name in requires if shutil.which(name) is None]
    if missing:
        return _fail(
            f"{script_name} butuh: {', '.join(missing)} (tidak ditemukan di PATH)",
            "jalankan: cs21 doctor --fix",
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

    rc = _run_engine("cs20_engine.py", passthrough, quiet_stdout=args.json,
                     requires=("yt-dlp",))
    if args.json:
        print(json.dumps({
            "channel": channel,
            "mode": mode,
            "limit": args.limit,
            "exit": rc,
            "ok": rc == 0,
        }, ensure_ascii=False, indent=2))
    if rc != 0:
        # Exit 4 = dependensi (preflight sudah mencetak pesan + saran sendiri).
        if rc == int(ExitCode.DEPENDENCY):
            return int(ExitCode.DEPENDENCY)
        print(
            f"error: scan berhenti dengan kode {rc}"
            + (f" (channel: {channel})" if channel else ""),
            file=sys.stderr,
        )
        print("saran: cek nama channel, koneksi, lalu `cs21 doctor`", file=sys.stderr)
        return int(rc) if rc in (0, 1, 2, 3, 130) else int(ExitCode.FAIL)
    return int(ExitCode.OK)

# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def _cmd_cache(args) -> int:
    from . import cache as _cache

    root = args.cache_dir or None
    as_json = getattr(args, "json", False)
    with _json_stdout(as_json) as out:
        if args.cache_cmd == "purge":
            n = _cache.purge(
                video_id=args.video,
                lang=args.lang,
                channel=args.channel,
                all=args.all,
                max_age_days=args.max_age,
                root=root,
            )
            if as_json:
                print(json.dumps({"removed": n}, indent=2), file=out)
            else:
                print(f"purge: {n} file dihapus")
            return int(ExitCode.OK)
        if args.cache_cmd == "gc":
            n = _cache.gc(root=root, ttl_days=args.ttl_days)
            if as_json:
                print(json.dumps({"removed": n}, indent=2), file=out)
            else:
                print(f"gc: {n} file kedaluwarsa dihapus")
            return int(ExitCode.OK)
        if args.cache_cmd == "stats":
            return _cache_stats(root, as_json=as_json, out=out)
    return _fail("subcommand cache tidak dikenal", "pilih: purge | gc | stats", ExitCode.USAGE)

def _cache_stats(root, *, as_json: bool = False, out=None) -> int:
    from . import cache as _cache

    out = out or sys.stdout
    data = _cache.stats(root)
    if as_json:
        payload = dict(data, human=_human_size(data["bytes"]))
        payload["roots"] = [
            dict(row, human=_human_size(row["bytes"])) for row in data["roots"]
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        return int(ExitCode.OK)
    print(f"cache dir : {data['dir']}  (primer)")
    print(f"files     : {data['files']}")
    print(f"size      : {_human_size(data['bytes'])}")
    extra = [row for row in data["roots"] if not row["primary"] and row["files"]]
    for row in extra:
        print(f"  + {row['dir']}  ({row['files']} file, {_human_size(row['bytes'])})")
    return int(ExitCode.OK)

def _cmd_report(args) -> int:
    from . import reports as _reports
    from . import termux as _termux

    as_json = getattr(args, "json", False)
    folder = Path(args.dir).expanduser() if args.dir else None

    if args.report_cmd == "list":
        items = _reports.list_reports(folder)
        if as_json:
            print(json.dumps([
                {"path": str(r.path), "label": r.label, "size": r.size,
                 "when": r.when, "mtime": int(r.mtime)}
                for r in items
            ], ensure_ascii=False, indent=2))
            return int(ExitCode.OK)
        if not items:
            print(f"(belum ada laporan di {_reports.reports_dir(create=False)})")
            return int(ExitCode.OK)
        print(f"{len(items)} laporan di {_reports.reports_dir(create=False)}")
        rows = [(r.when, _human_size(r.size), r.label, str(r.path)) for r in items[: args.limit]]
        _print_table(("WAKTU", "UKURAN", "LABEL", "FILE"), rows)
        if len(items) > len(rows):
            print(f"  … +{len(items) - len(rows)} lagi (--limit)")
        return int(ExitCode.OK)

    if args.report_cmd == "open":
        target = _resolve_report(args.target, folder)
        if target is None:
            return _fail("laporan tidak ditemukan", "cs21 report list", ExitCode.USAGE)
        if as_json:
            print(json.dumps({"path": str(target)}, ensure_ascii=False))
            return int(ExitCode.OK)
        if not _termux.open_file(target):
            print(f"laporan: {target}")
            print("catatan: Termux:API tidak tersedia — buka manual di atas", file=sys.stderr)
        return int(ExitCode.OK)

    if args.report_cmd == "rm":
        if not args.target and args.older_than is None and args.keep is None:
            return _fail("sebutkan target", 'contoh: cs21 report rm --keep 10', ExitCode.USAGE)
        removed = 0
        if args.target:
            target = _resolve_report(args.target, folder)
            if target is None:
                return _fail("laporan tidak ditemukan", "cs21 report list", ExitCode.USAGE)
            try:
                target.unlink()
                removed = 1
            except OSError as exc:
                return _fail(f"gagal menghapus: {exc}", "", ExitCode.FAIL)
        if args.keep is not None:
            removed += _reports.prune(keep=args.keep, folder=folder)
        if args.older_than is not None:
            removed += _prune_older(folder, args.older_than)
        if as_json:
            print(json.dumps({"removed": removed}, indent=2))
        else:
            print(f"rm: {removed} laporan dihapus")
        return int(ExitCode.OK)

    return _fail("subcommand report tidak dikenal", "pilih: list | open | rm", ExitCode.USAGE)

def _resolve_report(target: str, folder) -> Path | None:
    """`target` boleh path penuh, nama file, atau awalan label."""
    from . import reports as _reports

    if not target:
        latest = _reports.latest(folder)
        return latest.path if latest else None
    path = Path(target).expanduser()
    if path.is_file():
        return path
    items = _reports.list_reports(folder)
    for rep in items:
        if rep.path.name == target:
            return rep.path
    matches = [rep for rep in items if target.lower() in rep.label.lower()]
    if len(matches) == 1:
        return matches[0].path
    if len(matches) > 1:
        print(f"ambigu: {len(matches)} laporan cocok dengan {target!r}", file=sys.stderr)
        for rep in matches[:5]:
            print(f"  {rep.path.name}", file=sys.stderr)
    return None

def _prune_older(folder, days: int) -> int:
    from . import reports as _reports

    cutoff = _time.time() - days * 86400
    removed = 0
    for rep in _reports.list_reports(folder):
        if rep.mtime >= cutoff:
            continue
        try:
            rep.path.unlink()
            removed += 1
        except OSError:
            continue
    return removed

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

    p_analyze = sub.add_parser("analyze", help="fetch transcript + scoring (boleh banyak video)")
    p_analyze.add_argument("--video", action="append", default=None, metavar="ID_ATAU_URL",
                           help="video ID/URL; boleh diulang atau dipisah koma")
    p_analyze.add_argument("--from-file", default="", dest="from_file", metavar="FILE",
                           help="baca daftar video dari file (satu per baris, # komentar)")
    p_analyze.add_argument("--lang", default="id", help="id/en/jp/kr/in/th")
    p_analyze.add_argument("--cache-dir", default="", help="root cache transcript")
    p_analyze.add_argument("--executor", default="", help="nama operator di laporan HTML")
    p_analyze.add_argument("--html", action="store_true", help="tulis laporan HTML")
    p_analyze.add_argument("--open", action="store_true",
                           help="buka laporan HTML setelah dibuat (Android)")
    p_analyze.add_argument("--json", action="store_true", help="output JSON murni")
    p_analyze.add_argument("--refresh", action="store_true", help="paksa fetch ulang")
    p_analyze.set_defaults(func=_cmd_analyze)

    p_search = sub.add_parser("search", help="cari query di JSON index + cache transkrip")
    p_search.add_argument("--query", required=True, help="query pencarian")
    p_search.add_argument("--index-dir", default="", help="root index (default: root cache primer)")
    p_search.add_argument("--cache-dir", default="", help="root cache transcript (default: otomatis)")
    p_search.add_argument("--channel", default="", help="filter/label channel (opsional)")
    p_search.add_argument("--source", action="append", choices=("index", "cache"),
                          default=None, help="sumber pencarian (boleh diulang; default: keduanya)")
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
    p_index.set_defaults(func=lambda a: _run_engine(
        "cs20_index_engine.py", a.passthrough, requires=("yt-dlp",)))

    p_age = sub.add_parser("age", help="delegasi ke cs20_age_engine.py")
    p_age.add_argument("passthrough", nargs=argparse.REMAINDER)
    p_age.set_defaults(func=lambda a: _run_engine(
        "cs20_age_engine.py", a.passthrough, requires=("yt-dlp",)))

    p_cache = sub.add_parser("cache", help="kelola cache transcript")
    p_cache.add_argument("--cache-dir", default="", help="root cache transcript")
    p_cache.add_argument("--json", action="store_true",
                         help="output JSON murni (boleh sebelum/sesudah subcommand)")
    cache_sub = p_cache.add_subparsers(dest="cache_cmd", required=True)
    # `default=SUPPRESS`: subparser tidak menimpa `--json` yang sudah diberikan
    # di level `cache` (argparse menimpa dengan default bila tidak diset).
    _json_kw = {"action": "store_true", "default": argparse.SUPPRESS,
                "help": "output JSON murni"}

    c_purge = cache_sub.add_parser("purge", help="hapus file cache")
    c_purge.add_argument("--video", default=None)
    c_purge.add_argument("--lang", default=None)
    c_purge.add_argument("--channel", default=None)
    c_purge.add_argument("--all", action="store_true")
    c_purge.add_argument("--max-age", type=int, default=None, dest="max_age")
    c_purge.add_argument("--json", **_json_kw)
    c_purge.set_defaults(func=_cmd_cache)

    c_gc = cache_sub.add_parser("gc", help="sapu cache kedaluwarsa")
    c_gc.add_argument("--ttl-days", type=int, default=None, dest="ttl_days")
    c_gc.add_argument("--json", **_json_kw)
    c_gc.set_defaults(func=_cmd_cache)

    c_stats = cache_sub.add_parser("stats", help="statistik cache")
    c_stats.add_argument("--json", **_json_kw)
    c_stats.set_defaults(func=_cmd_cache)

    p_report = sub.add_parser("report", help="kelola laporan HTML")
    p_report.add_argument("--dir", default="", help="folder laporan (default: otomatis)")
    p_report.add_argument("--json", action="store_true",
                          help="output JSON murni (boleh sebelum/sesudah subcommand)")
    report_sub = p_report.add_subparsers(dest="report_cmd", required=True)
    _report_json = {"action": "store_true", "default": argparse.SUPPRESS,
                    "help": "output JSON murni"}

    r_list = report_sub.add_parser("list", help="daftar laporan")
    r_list.add_argument("--limit", type=int, default=20)
    r_list.add_argument("--json", **_report_json)
    r_list.set_defaults(func=_cmd_report)

    r_open = report_sub.add_parser("open", help="buka laporan (default: terbaru)")
    r_open.add_argument("target", nargs="?", default="",
                        help="nama file / potongan label (kosong = terbaru)")
    r_open.add_argument("--json", **_report_json)
    r_open.set_defaults(func=_cmd_report)

    r_rm = report_sub.add_parser("rm", help="hapus laporan")
    r_rm.add_argument("target", nargs="?", default="", help="nama file / potongan label")
    r_rm.add_argument("--keep", type=int, default=None, help="sisakan N laporan terbaru")
    r_rm.add_argument("--older-than", type=int, default=None, dest="older_than",
                      metavar="HARI", help="hapus yang lebih tua dari N hari")
    r_rm.add_argument("--json", **_report_json)
    r_rm.set_defaults(func=_cmd_report)

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
        return _run_engine(script, argv_eff[1:], requires=("yt-dlp",))

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
