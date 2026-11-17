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
import re
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
    # `CS_COMPAT` menentukan label kasta (default BASELINE, sesuai README).
    # Sebelumnya hardcode IMPROVED sehingga env itu tidak berpengaruh.
    legacy = to_legacy(result, mode=CompatMode.from_env(), engine="E")

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

        if args.playlist:
            from .playlists import playlist_video_ids

            try:
                allowed = set(playlist_video_ids(
                    args.playlist, config_dir=args.config_dir or None
                ))
            except CsError as exc:
                return _fail(exc.message, exc.hint, exc.code)
            results = [r for r in results if r.video_id in allowed]

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
    from .engine_compat import CONTENT_TYPES, normalize_content_type
    from .settings import load as _load_settings

    channel = (args.channel or "").strip().lstrip("@")
    if not channel:
        return _fail("--channel wajib diisi", "contoh: cs21 scan --channel windahbasudara", ExitCode.USAGE)
    lang = resolve_lang(args.lang)

    raw_ct = (args.content_type or "").strip().lower()
    if raw_ct and raw_ct not in CONTENT_TYPES:
        return _fail(
            f"--content-type '{raw_ct}' tidak dikenal",
            "pilihan: all | video | live (atau kosongkan untuk ikut setelan)",
            ExitCode.USAGE,
        )
    content_type = normalize_content_type(
        raw_ct or _load_settings(args.config_dir or None).content_type
    )
    _ensure_config_dir(args.config_dir)

    mode = "pantau" if args.ui else "plain"
    passthrough = [
        "--channel", channel,
        "--limit", str(args.limit),
        "--jobs", str(args.jobs),
        "--content-type", content_type,
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
    if args.video_ids:
        passthrough += ["--video-ids", args.video_ids]
    if args.new_only:
        passthrough += ["--new-only"]

    rc = _run_engine("cs20_engine.py", passthrough, quiet_stdout=args.json,
                     requires=("yt-dlp",))
    if args.json:
        print(json.dumps({
            "channel": channel,
            "mode": mode,
            "limit": args.limit,
            "content_type": content_type,
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
# watch
# ---------------------------------------------------------------------------
def _parse_interval(text: str) -> float:
    match = re.fullmatch(r"\s*(\d+)\s*([smh]?)\s*", (text or "").lower())
    if not match:
        raise ValueError("format interval: 30s, 15m, 2h")
    value = int(match.group(1))
    unit = match.group(2) or "m"
    factor = {"s": 1, "m": 60, "h": 3600}[unit]
    seconds = value * factor
    if seconds < 30:
        raise ValueError("interval minimal 30 detik")
    return float(seconds)

def _webhook_from_file(config_dir: str, lang: str) -> str:
    path = Path(config_dir or _settings.config_dir()) / ".webhook_injected"
    hooks: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            hooks[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    key = "WEBHOOK_INDONESIA" if lang == "id" else "WEBHOOK_GLOBAL"
    return hooks.get(key) or os.environ.get("CS_WEBHOOK", "")

def _watch_channels(args) -> list[str]:
    raw: list[str] = []
    for item in (args.channel or []):
        raw.extend(part.strip() for part in item.split(",") if part.strip())
    if args.all:
        from .menu import load_saved_channels

        raw.extend(load_saved_channels(args.config_dir or None))
    seen, out = set(), []
    for channel in raw:
        if channel not in seen:
            seen.add(channel)
            out.append(channel)
    return out

def _watch_pass(channels: list[str], args, *, lang: str, content_type: str,
                jobs: int, webhook: str, checkpoint_dir: str) -> tuple[list[dict], int]:
    from .feed import channel_latest
    from .watch import filter_new, get, mark_seen, touch

    cfg = args.config_dir or None
    limit = max(1, min(15, int(args.limit)))
    results: list[dict] = []
    worst = 0

    for index, channel in enumerate(channels, 1):
        info = channel_latest(channel, config_dir=cfg, limit=15,
                              use_search=True)
        if info is None or info.error == "error":
            results.append({"channel": channel, "status": "feed_error"})
            print(f"[{index}/{len(channels)}] {channel}: feed tidak tersedia",
                  file=sys.stderr)
            continue

        new = filter_new(info.channel_id, info.videos, cfg)
        if not new:
            touch(info.channel_id, cfg)
            results.append({
                "channel": channel, "channel_id": info.channel_id,
                "name": info.name, "status": "no_new", "new": [],
            })
            print(f"[{index}/{len(channels)}] {info.name or channel}: tidak ada video baru",
                  file=sys.stderr)
            continue

        # Run pertama = baseline: ambil yang terbaru. Setelah ada kursor,
        # backlog diproses dari potongan tertua agar tidak ada yang terlewat.
        first_run = not get(info.channel_id, cfg).get("last_video_id")
        selected = new[:limit] if first_run else new[-limit:]
        ids = [v.video_id for v in selected]
        print(f"[{index}/{len(channels)}] {info.name or channel}: "
              f"{len(selected)} video baru", file=sys.stderr)
        for video in selected:
            print(f"    - {video.video_id}  {video.published[:10]}  {video.title[:60]}",
                  file=sys.stderr)

        if args.dry_run:
            results.append({
                "channel": channel, "channel_id": info.channel_id,
                "name": info.name, "status": "dry_run", "new": ids,
            })
            continue

        passthrough = [
            "--channel", info.channel_id,
            "--video-ids", ",".join(ids),
            "--limit", str(len(ids)),
            "--jobs", str(jobs),
            "--content-type", content_type,
            "--executor", args.executor,
            "--mode", "plain",
            "--start-from", "0",
            "--checkpoint-dir", checkpoint_dir,
            "--config-dir", str(cfg or _settings.config_dir()),
            "--lang", lang,
        ]
        if info.name:
            passthrough += ["--display-name", info.name]
        if webhook:
            passthrough += ["--webhook-url", webhook]

        rc = _run_engine("cs20_engine.py", passthrough,
                         quiet_stdout=args.json, requires=("yt-dlp",))
        if rc == 0:
            mark_seen(info.channel_id, selected, cfg)
        else:
            worst = max(worst, rc)
        results.append({
            "channel": channel, "channel_id": info.channel_id,
            "name": info.name, "status": "scanned" if rc == 0 else "failed",
            "rc": rc, "new": ids,
        })

        if index < len(channels) and args.channel_delay > 0:
            _time.sleep(args.channel_delay)

    return results, worst

def _cmd_watch(args) -> int:
    from . import store
    from .engine_compat import CONTENT_TYPES, normalize_content_type
    from .settings import load as _load_settings

    try:
        store.require()
    except DependencyError as exc:
        return _fail(exc.message, exc.hint, exc.code)

    channels = _watch_channels(args)
    if not channels:
        return _fail("--channel atau --all wajib diisi",
                     "contoh: cs21 watch --channel @aerithlive --once",
                     ExitCode.USAGE)
    if len(channels) > args.max_channels:
        _warn(f"{len(channels)} channel > --max-channels {args.max_channels}; "
              f"hanya {args.max_channels} pertama dipakai")
        channels = channels[:args.max_channels]
    if not channels:
        return _fail("tidak ada channel untuk dipantau", "", ExitCode.USAGE)

    try:
        interval = _parse_interval(args.interval)
    except ValueError as exc:
        return _fail(str(exc), "contoh: --interval 30m", ExitCode.USAGE)

    lang = resolve_lang(args.lang)
    raw_ct = (args.content_type or "").strip().lower()
    if raw_ct and raw_ct not in CONTENT_TYPES:
        return _fail(f"--content-type '{raw_ct}' tidak dikenal",
                     "pilihan: all | video | live", ExitCode.USAGE)
    settings = _load_settings(args.config_dir or None)
    content_type = normalize_content_type(raw_ct or settings.content_type)
    jobs = args.jobs or settings.jobs
    cfg = args.config_dir or str(_settings.config_dir())
    checkpoint_dir = args.checkpoint_dir or str(Path(cfg) / "checkpoints")
    webhook = args.webhook_url or _webhook_from_file(cfg, lang)

    pass_no = 0
    worst = 0
    with _json_stdout(args.json) as out:
        while True:
            pass_no += 1
            results, rc = _watch_pass(
                channels, args, lang=lang, content_type=content_type,
                jobs=jobs, webhook=webhook, checkpoint_dir=checkpoint_dir,
            )
            worst = max(worst, rc)
            if args.json:
                print(json.dumps({
                    "pass": pass_no,
                    "channels": results,
                }, ensure_ascii=False, indent=2), file=out, flush=True)
            if args.once:
                break
            _time.sleep(interval)
    return int(worst)

# ---------------------------------------------------------------------------
# playlist
# ---------------------------------------------------------------------------
def _cmd_playlist(args) -> int:
    from .engine_compat import CONTENT_TYPES, normalize_content_type
    from .settings import load as _load_settings

    lang = resolve_lang(args.lang)
    raw_ct = (args.content_type or "").strip().lower()
    if raw_ct and raw_ct not in CONTENT_TYPES:
        return _fail(f"--content-type '{raw_ct}' tidak dikenal",
                     "pilihan: all | video | live", ExitCode.USAGE)
    settings = _load_settings(args.config_dir or None)
    content_type = normalize_content_type(raw_ct or settings.content_type)
    cfg = args.config_dir or str(_settings.config_dir())
    checkpoint_dir = args.checkpoint_dir or str(Path(cfg) / "checkpoints")
    webhook = args.webhook_url or _webhook_from_file(cfg, lang)

    passthrough = [
        "--playlist", args.url,
        "--limit", str(args.limit),
        "--start", str(args.start),
        "--lang", lang,
        "--jobs", str(args.jobs or settings.jobs),
        "--content-type", content_type,
        "--executor", args.executor,
        "--mode", "pantau" if args.ui else "plain",
        "--config-dir", cfg,
        "--checkpoint-dir", checkpoint_dir,
    ]
    if webhook:
        passthrough += ["--webhook-url", webhook]
    if args.json:
        passthrough += ["--json"]
    if args.dry_run:
        passthrough += ["--dry-run"]
    return _run_engine("cs20_playlist_engine.py", passthrough,
                       requires=("yt-dlp",))

# ---------------------------------------------------------------------------
# cookies
# ---------------------------------------------------------------------------
def _read_pasted_cookies() -> str:
    lines: list[str] = []
    if sys.stdin.isatty():
        print("paste cookies Netscape; akhiri dengan baris kosong:", file=sys.stderr)
    for line in sys.stdin:
        if not line.strip():
            break
        lines.append(line.rstrip("\n"))
    return "\n".join(lines)

def _cmd_cookies(args) -> int:
    from . import cookies

    as_json = getattr(args, "json", False)
    cfg = args.config_dir or None
    try:
        if args.clear:
            ok = cookies.clear(cfg)
            if as_json:
                print(json.dumps({"cleared": ok}, ensure_ascii=False, indent=2))
            else:
                print("cookies dihapus" if ok else "tidak ada cookies untuk dihapus")
            return int(ExitCode.OK)

        if args.file:
            st = cookies.import_file(args.file, cfg)
        elif args.paste:
            text = _read_pasted_cookies()
            if not text.strip():
                return _fail("tidak ada cookies yang dipaste", "", ExitCode.USAGE)
            st = cookies.save_text(text, cfg)
        else:
            st = cookies.status(cfg)

        check = cookies.validate(cfg, args.url) if args.check else None
        if as_json:
            payload = {
                "path": str(st.path), "exists": st.exists, "size": st.size,
                "count": st.count, "has_login": st.has_login,
                "names": list(st.names),
            }
            if check:
                payload["check"] = {
                    "ok": check.ok, "message": check.message,
                    "detail": check.detail,
                }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return int(ExitCode.OK if (check is None or check.ok) else ExitCode.FAIL)

        print(f"file       {st.path}")
        print(f"status     {'ada' if st.exists else 'belum ada'}")
        if st.exists:
            print(f"ukuran     {st.size} B · {st.count} cookie · login={'ya' if st.has_login else 'tidak'}")
            print(f"umur       {st.age_days:.1f} hari")
        if check:
            print(f"cek        {'OK' if check.ok else 'GAGAL'} — {check.message}")
            if check.detail:
                print(f"detail     {check.detail}")
        return int(ExitCode.OK if (check is None or check.ok) else ExitCode.FAIL)
    except ValueError as exc:
        return _fail(str(exc), "pastikan format Netscape (7 kolom tab)", ExitCode.USAGE)

# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
def _fmt_ts(ts: float) -> str:
    try:
        return _time.strftime("%d %b %H:%M", _time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "?"

def _run_label(run: dict) -> str:
    return str(run.get("name") or run.get("channel") or "?")

def _cmd_runs(args) -> int:
    from . import store

    try:
        store.require()
    except DependencyError as exc:
        return _fail(exc.message, exc.hint, exc.code)

    as_json = getattr(args, "json", False)
    cfg = args.config_dir or None
    cmd = args.runs_cmd

    if cmd == "list":
        runs = store.list_runs(args.limit, args.channel, cfg)
        if as_json:
            print(json.dumps(runs, ensure_ascii=False, indent=2))
            return int(ExitCode.OK)
        if not runs:
            print("(belum ada run)")
            return int(ExitCode.OK)
        rows = [
            (str(r["id"]), _fmt_ts(r["started_at"]), _run_label(r),
             str(r["lang"]), str(r["total"]), str(r["valid"]),
             str(r["hits"]), str(r["score"]), str(r["status"]))
            for r in runs
        ]
        widths = [4, 14, 24, 5, 6, 6, 6, 6, 8]
        print("  " + "  ".join(h.ljust(w) for h, w in zip(
            ("ID", "Waktu", "Channel", "Lang", "Total", "Valid", "Hits", "Score", "Status"),
            widths)))
        for row in rows:
            print("  " + "  ".join(str(c)[:w].ljust(w) for c, w in zip(row, widths)))
        return int(ExitCode.OK)

    if cmd == "show":
        run = store.get_run(args.run_id, cfg)
        if run is None:
            return _fail(f"run {args.run_id} tidak ditemukan", "", ExitCode.FAIL)
        if as_json:
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return int(ExitCode.OK)
        print(f"run {run['id']} — {_run_label(run)}")
        print(f"channel   {run['channel']}")
        print(f"waktu     {_fmt_ts(run['started_at'])} → {_fmt_ts(run['finished_at'])}")
        print(f"mode      {run['mode']} | lang {run['lang']} | konten {run['content_type']}")
        print(f"total     {run['total']} | valid {run['valid']} | hits {len(run['hits'])} | score {run['score']}")
        print(f"status    {run['status']}")
        if run["videos"]:
            print("\nvideo:")
            for v in run["videos"]:
                print(f"  {v['video_id']}  {v['status']:<14} score={v['score']:<3} "
                      f"{v['persentase']:>3}%  {v['kasta']:<10} hits={v['hits']}")
        if run["hits"]:
            print("\nhit:")
            for h in run["hits"]:
                print(f"  {h['video_id']}  {h['time']}  {h['text'][:70]}")
        return int(ExitCode.OK)

    if cmd == "diff":
        diff = store.diff_runs(args.a, args.b, cfg)
        if diff is None:
            return _fail(f"run {args.a} atau {args.b} tidak ditemukan", "", ExitCode.FAIL)
        if as_json:
            print(json.dumps({
                "a": diff["a"]["id"], "b": diff["b"]["id"],
                "new_hits": diff["new_hits"],
                "removed_hits": diff["removed_hits"],
                "score_changes": diff["score_changes"],
            }, ensure_ascii=False, indent=2))
            return int(ExitCode.OK)
        print(f"run {diff['a']['id']} → {diff['b']['id']}")
        print(f"hit baru   {len(diff['new_hits'])}")
        for h in diff["new_hits"]:
            print(f"  + {h['video_id']}  {h['time']}  {h['text'][:70]}")
        print(f"hit hilang {len(diff['removed_hits'])}")
        for h in diff["removed_hits"]:
            print(f"  - {h['video_id']}  {h['time']}  {h['text'][:70]}")
        print(f"skor berubah {len(diff['score_changes'])}")
        for c in diff["score_changes"]:
            print(f"  {c['video_id']}  {c['old']} → {c['new']} ({c['delta']:+d})")
        return int(ExitCode.OK)

    return _fail(f"perintah runs tidak dikenal: {cmd}", "", ExitCode.USAGE)

# ---------------------------------------------------------------------------
# channel-id
# ---------------------------------------------------------------------------
def _cmd_channel_id(args) -> int:
    from .channels import AmbiguousChannel, append_channel, resolve_channel

    cfg = args.config_dir or None
    with _json_stdout(args.json) as out:
        try:
            res = resolve_channel(
                args.target,
                use_search=not args.no_search,
                config_dir=cfg,
                refresh=args.refresh,
            )
        except AmbiguousChannel as exc:
            if args.json:
                print(json.dumps({
                    "input": args.target,
                    "ambiguous": True,
                    "error": exc.message,
                    "candidates": [c.as_dict() for c in exc.candidates],
                }, ensure_ascii=False, indent=2), file=out)
            return _fail(
                exc.message,
                "pilih ID dari daftar kandidat, atau pakai URL video dari kanal target",
                exc.code,
            )
        except CsError as exc:
            if args.json:
                print(json.dumps({
                    "input": args.target,
                    "error": exc.message,
                }, ensure_ascii=False, indent=2), file=out)
            return _fail(exc.message, exc.hint, exc.code)

        saved = append_channel(res.channel_id, cfg) if args.save else False
        if args.json:
            payload = res.as_dict()
            payload["saved"] = saved
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
            return int(ExitCode.OK)

        print(f"input      {res.input}")
        if res.redirected:
            print("redirect   handle dialihkan YouTube ke kanal lain")
        if res.name:
            print(f"nama       {res.name}")
        if res.handle and res.handle.lower() != (args.target or "").strip().lower():
            print(f"handle     {res.handle}")
        if res.candidates:
            for cand in res.candidates[:5]:
                print(f"kandidat   {cand.channel_id}  {cand.name}  "
                      f"({cand.hits} hasil)")
        print(f"hasil      {res.channel_id}")
        if res.warning:
            print(f"catatan    {res.warning}")
        if args.save:
            print("disimpan   " + ("ya (channels.txt)" if saved else "sudah ada"))
    return int(ExitCode.OK)

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
    p_search.add_argument("--playlist", default="",
                          help="batasi hasil ke video playlist (URL/ID)")
    p_search.add_argument("--source", action="append", choices=("index", "cache"),
                          default=None, help="sumber pencarian (boleh diulang; default: keduanya)")
    p_search.add_argument("--json", action="store_true", help="output JSON murni")
    p_search.set_defaults(func=_cmd_search)

    p_scan = sub.add_parser("scan", help="scan channel non-interaktif (plain default)")
    p_scan.add_argument("--channel", required=True, help="handle / channel_id / URL")
    p_scan.add_argument("--lang", default="id", help="id/en/jp/kr/in/th")
    p_scan.add_argument("--limit", type=int, default=50, help="jumlah video (<=0 = semua)")
    p_scan.add_argument("--jobs", type=int, default=4, help="worker paralel")
    p_scan.add_argument("--content-type", default="",
                        help="live | video | all (kosong = ikut setelan menu)",
                        dest="content_type")
    p_scan.add_argument("--executor", default="cli", help="nama operator di laporan")
    p_scan.add_argument("--start-from", type=int, default=0, dest="start_from")
    p_scan.add_argument("--checkpoint-dir", default="", dest="checkpoint_dir")
    p_scan.add_argument("--config-dir", default=argparse.SUPPRESS, dest="config_dir")
    p_scan.add_argument("--webhook-url", default="", dest="webhook_url",
                        help="URL Discord; kosong = tanpa kirim laporan")
    p_scan.add_argument("--display-name", default="", dest="display_name")
    p_scan.add_argument("--retry-blocked-log", default="", dest="retry_blocked_log")
    p_scan.add_argument("--video-ids", default="", dest="video_ids",
                        help="daftar video ID eksplisit (dipisah koma)")
    p_scan.add_argument("--new-only", action="store_true", dest="new_only",
                        help="hanya video baru dari kursor watch_state")
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

    p_watch = sub.add_parser(
        "watch",
        help="pantau video baru via RSS lalu scan otomatis",
    )
    p_watch.add_argument("--channel", action="append", default=None,
                         help="handle/ID/URL; boleh diulang atau dipisah koma")
    p_watch.add_argument("--all", action="store_true",
                         help="pakai semua channel di channels.txt")
    p_watch.add_argument("--interval", default="30m",
                         help="jeda antar-pass: 30s/15m/2h (default 30m)")
    p_watch.add_argument("--once", action="store_true",
                         help="jalankan satu pass lalu keluar")
    p_watch.add_argument("--limit", type=int, default=5,
                         help="maksimal video baru per channel per pass (1–15)")
    p_watch.add_argument("--lang", default="id", help="id/en/jp/kr/in/th")
    p_watch.add_argument("--content-type", default="", dest="content_type",
                         help="live | video | all (kosong = ikut setelan)")
    p_watch.add_argument("--jobs", type=int, default=0,
                         help="worker paralel (0 = ikut setelan)")
    p_watch.add_argument("--executor", default="watch",
                         help="nama operator di laporan")
    p_watch.add_argument("--webhook-url", default="", dest="webhook_url",
                         help="URL Discord; kosong = baca .webhook_injected")
    p_watch.add_argument("--config-dir", default=argparse.SUPPRESS, dest="config_dir")
    p_watch.add_argument("--checkpoint-dir", default="", dest="checkpoint_dir")
    p_watch.add_argument("--max-channels", type=int, default=20,
                         dest="max_channels")
    p_watch.add_argument("--channel-delay", type=float, default=3.0,
                         dest="channel_delay",
                         help="jeda antar-channel (detik)")
    p_watch.add_argument("--dry-run", action="store_true", dest="dry_run",
                         help="tampilkan video baru tanpa scan")
    p_watch.add_argument("--json", action="store_true", help="output JSON per pass")
    p_watch.set_defaults(func=_cmd_watch)

    p_playlist = sub.add_parser("playlist", help="scan khusus playlist YouTube")
    p_playlist.add_argument("--url", required=True,
                            help="URL/ID playlist (PL…, UU…, UUMO…, OLAK5uy…, RD…)")
    p_playlist.add_argument("--limit", type=int, default=50,
                            help="jumlah video (<=0 = semua)")
    p_playlist.add_argument("--start", type=int, default=1,
                            help="mulai dari item playlist ke-N")
    p_playlist.add_argument("--lang", default="id", help="id/en/jp/kr/in/th")
    p_playlist.add_argument("--jobs", type=int, default=0,
                            help="worker paralel (0 = ikut setelan)")
    p_playlist.add_argument("--content-type", default="", dest="content_type",
                            help="all | video | live (kosong = ikut setelan)")
    p_playlist.add_argument("--executor", default="playlist")
    p_playlist.add_argument("--config-dir", default=argparse.SUPPRESS,
                            dest="config_dir")
    p_playlist.add_argument("--checkpoint-dir", default="", dest="checkpoint_dir")
    p_playlist.add_argument("--webhook-url", default="", dest="webhook_url")
    p_playlist.add_argument("--ui", action="store_true",
                            help="pakai dashboard Live")
    p_playlist.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_playlist.add_argument("--json", action="store_true")
    p_playlist.set_defaults(func=_cmd_playlist)

    p_cookies = sub.add_parser("cookies", help="import/paste/cek cookies YouTube")
    p_cookies.add_argument("--file", default="", help="import cookies.txt")
    p_cookies.add_argument("--paste", action="store_true",
                           help="baca cookies Netscape dari stdin")
    p_cookies.add_argument("--check", action="store_true",
                           help="cek cookies lewat yt-dlp")
    p_cookies.add_argument("--url", default="",
                           help="URL video member untuk cek akses (opsional)")
    p_cookies.add_argument("--clear", action="store_true", help="hapus cookies")
    p_cookies.add_argument("--config-dir", default=argparse.SUPPRESS,
                           dest="config_dir")
    p_cookies.add_argument("--json", action="store_true")
    p_cookies.set_defaults(func=_cmd_cookies)

    p_runs = sub.add_parser("runs", help="riwayat run, detail, dan diff")
    p_runs.add_argument("--json", action="store_true",
                        help="output JSON murni")
    runs_sub = p_runs.add_subparsers(dest="runs_cmd", required=True)
    _runs_json = {"action": "store_true", "default": argparse.SUPPRESS,
                  "help": "output JSON murni"}

    r_list = runs_sub.add_parser("list", help="daftar run terakhir")
    r_list.add_argument("--limit", type=int, default=20)
    r_list.add_argument("--channel", default="", help="filter channel/ID")
    r_list.add_argument("--json", **_runs_json)
    r_list.set_defaults(func=_cmd_runs)

    r_show = runs_sub.add_parser("show", help="detail satu run")
    r_show.add_argument("run_id", type=int)
    r_show.add_argument("--json", **_runs_json)
    r_show.set_defaults(func=_cmd_runs)

    r_diff = runs_sub.add_parser("diff", help="bandingkan dua run")
    r_diff.add_argument("a", type=int)
    r_diff.add_argument("b", type=int)
    r_diff.add_argument("--json", **_runs_json)
    r_diff.set_defaults(func=_cmd_runs)

    p_channel = sub.add_parser(
        "channel-id",
        help="deteksi channel ID dari handle / URL kanal / URL video",
    )
    p_channel.add_argument("target",
                           help="@handle, URL kanal, URL/ID video, atau UC…")
    p_channel.add_argument("--json", action="store_true", help="output JSON murni")
    p_channel.add_argument("--save", action="store_true",
                           help="tambahkan channel ID ke channels.txt")
    p_channel.add_argument("--refresh", action="store_true",
                           help="abaikan cache channel_ids.json")
    p_channel.add_argument("--no-search", action="store_true", dest="no_search",
                           help="jangan cari kandidat saat handle dialihkan")
    p_channel.set_defaults(func=_cmd_channel_id)

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
