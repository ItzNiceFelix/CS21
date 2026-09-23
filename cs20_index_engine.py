#!/usr/bin/env python3
# ==============================================================================
# 👑 CEGUKAN SEEKER V21.0 — INDEX ENGINE
# Orchestrator for Index Mode: download → analyse → search → Discord
# ==============================================================================

import argparse
import gc
import json
import os
import re
import sys
import time
import threading
import shutil
import signal
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn,
        TextColumn, TimeRemainingColumn, MofNCompleteColumn
    )
    from rich.layout import Layout
    from rich import box as rbox
    from rich.prompt import Prompt, Confirm
except ImportError:
    print("[❌] Install rich dulu: pip install rich --break-system-packages")
    sys.exit(1)

try:
    import requests as _req_lib
except ImportError:
    _req_lib = None

# Import parser module (same directory)
sys.path.insert(0, os.path.dirname(__file__))
from cs20_index_parser import (
    detect_cache_root,
    get_playlist_count,
    fetch_video_ids_range,
    download_and_index_video,
    search_index_batch,
    load_meta, save_meta,
    load_status, save_status, update_video_status,
    init_error_log, append_error_log, count_error_log,
    load_json_safe, save_json_safe,
    _tokenize_query,
)

# ==============================================================================
# CONSTANTS & GLOBALS
# ==============================================================================
_console    = Console()
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    with _print_lock:
        _console.print(*args, **kwargs)

_TERM_WIDTH = shutil.get_terminal_size(fallback=(42, 24)).columns
_BAR_WIDTH  = max(10, min(28, _TERM_WIDTH - 32))

# Live stats — diupdate tiap video selesai
_stats = {
    "phase":        "download",   # "download" | "analysis"
    "done":         0,
    "total":        0,
    "dl_ok":        0,
    "dl_no_sub":    0,
    "dl_unavail":   0,
    "dl_age":       0,
    "dl_ratelimit": 0,
    "dl_network":   0,
    "dl_error":     0,
    "dl_unknown":   0,
    "an_valid":     0,
    "an_hits":      0,
    "start_time":   0,
    "_jobs":        3,
}
_stats_lock = threading.Lock()

_current_batch_no  = 0
_current_error_log = ""
_cleanup_done      = False
_partial_results   = []

# ==============================================================================
# SESSION HELPERS
# ==============================================================================
def session_dir_for(cache_root: str, channel: str) -> str:
    path = os.path.join(cache_root, channel)
    os.makedirs(path, exist_ok=True)
    return path

def batch_dir_for(session_dir: str, batch_no: int) -> str:
    path = os.path.join(session_dir, f"batch_{batch_no:02d}")
    os.makedirs(path, exist_ok=True)
    return path

def index_dir_for(batch_dir: str) -> str:
    path = os.path.join(batch_dir, "index")
    os.makedirs(path, exist_ok=True)
    return path

def vtt_tmp_dir_for(batch_dir: str) -> str:
    path = os.path.join(batch_dir, "vtt_tmp")
    os.makedirs(path, exist_ok=True)
    return path

def error_log_path_for(batch_dir: str, channel: str, batch_no: int) -> str:
    return os.path.join(batch_dir, f"{channel}_batch{batch_no:02d}_errors.json")


# ==============================================================================
# DASHBOARD (mode PANTAU — rich Live)
# ==============================================================================
def _fmt_eta(done: int, total: int, start_time: float) -> str:
    if done == 0:
        return "menghitung..."
    elapsed   = time.time() - start_time
    rate      = done / elapsed
    remaining = (total - done) / rate if rate > 0 else 0
    m, s      = divmod(int(remaining), 60)
    return f"~{m}m {s}s"


def _make_dashboard(
    channel:    str,
    batch_no:   int,
    total_batches: int,
    batches_per_run: int,
) -> Table:
    s   = _stats
    pct = f"{s['done']*100//s['total']}%" if s["total"] else "0%"
    eta = _fmt_eta(s["done"], s["total"], s["start_time"])

    phase_label = (
        "[cyan]⬇️  DOWNLOAD[/cyan]"
        if s["phase"] == "download"
        else "[green]🔍 ANALYSIS[/green]"
    )

    tbl = Table(
        box=rbox.SIMPLE_HEAVY,
        show_header=False,
        width=min(_TERM_WIDTH - 2, 60),
        pad_edge=True,
    )
    tbl.add_column("k", style="dim",       width=18)
    tbl.add_column("v", style="bold white", width=36)

    tbl.add_row(
        "[bold cyan]INDEX MODE[/bold cyan]",
        f"[cyan]@{channel}[/cyan]"
    )
    tbl.add_row(
        "Batch",
        f"[white]{batch_no}[/white] / {total_batches}"
        f"  [dim](run {min(batch_no, batches_per_run)}/{batches_per_run})[/dim]"
    )
    tbl.add_row("Fase", phase_label)
    tbl.add_row(
        "Progress",
        f"[white]{s['done']}[/white] / {s['total']}  [cyan]{pct}[/cyan]"
    )
    tbl.add_row("ETA", f"[yellow]{eta}[/yellow]")
    tbl.add_row("", "")

    # Download stats
    tbl.add_row("[dim]── Download ──[/dim]", "")
    tbl.add_row(
        "[green]OK[/green]",
        f"[green]{s['dl_ok']}[/green]"
        f"    [dim]no_sub[/dim]  [yellow]{s['dl_no_sub']}[/yellow]"
    )
    tbl.add_row(
        "[dim]unavail[/dim]",
        f"[orange1]{s['dl_unavail']}[/orange1]"
        f"   [dim]age_restr[/dim] [orange1]{s['dl_age']}[/orange1]"
    )
    tbl.add_row(
        "[dim]ratelimit[/dim]",
        f"[red]{s['dl_ratelimit']}[/red]"
        f"   [dim]network[/dim]  [yellow]{s['dl_network']}[/yellow]"
    )
    tbl.add_row(
        "[dim]error[/dim]",
        f"[red]{s['dl_error']}[/red]"
        f"   [dim]unknown[/dim]  [red]{s['dl_unknown']}[/red]"
    )
    tbl.add_row("", "")

    # Analysis stats (muncul setelah fase download selesai)
    tbl.add_row("[dim]── Analysis ──[/dim]", "")
    if s["phase"] == "analysis":
        tbl.add_row(
            "[green]Valid[/green]",
            f"[green]{s['an_valid']} video[/green]"
        )
        tbl.add_row(
            "[magenta]Hits[/magenta]",
            f"[magenta]{s['an_hits']} momen[/magenta]"
        )
    else:
        tbl.add_row("[dim]menunggu download...[/dim]", "")

    return tbl


# ==============================================================================
# DOWNLOAD PHASE
# ==============================================================================
def run_download_phase(
    video_ids:    list,
    channel:      str,
    batch_no:     int,
    batch_dir:    str,
    lang:         str,
    jobs:         int,
    error_log:    str,
    total_batches: int,
    batches_per_run: int,
    config_dir:   str = "",
) -> dict:
    """
    Download subtitle + parse semua video_ids untuk satu batch.
    Return summary dict.
    """
    global _stats

    index_dir = index_dir_for(batch_dir)
    vtt_dir   = vtt_tmp_dir_for(batch_dir)

    # Init / load status
    status_data = load_status(batch_dir)
    if not status_data.get("videos"):
        status_data = {
            "batch_no": batch_no,
            "total":    len(video_ids),
            "done":     0,
            "videos":   {vid: "pending" for vid in video_ids},
        }
        save_status(batch_dir, status_data)

    # Cari yang belum diproses
    pending = [
        vid for vid in video_ids
        if status_data["videos"].get(vid) == "pending"
    ]

    if not pending:
        safe_print(f"[green][✅] Semua video batch {batch_no} sudah didownload.[/green]")
        return status_data

    with _stats_lock:
        _stats["phase"]      = "download"
        _stats["done"]       = status_data["total"] - len(pending)
        _stats["total"]      = status_data["total"]
        _stats["start_time"] = time.time()
        _stats["_jobs"]      = jobs

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=_BAR_WIDTH),
        MofNCompleteColumn(),
        TextColumn("[cyan]{task.percentage:>5.1f}%"),
        TimeRemainingColumn(),
        console=_console,
        transient=False,
    )
    task = progress.add_task(
        f"DL Batch {batch_no:02d}",
        total=status_data["total"],
        completed=_stats["done"],
    )

    layout = Layout()
    layout.split_column(
        Layout(name="dash",     ratio=5),
        Layout(name="progress", ratio=1),
    )
    layout["dash"].update(
        _make_dashboard(channel, batch_no, total_batches, batches_per_run)
    )
    layout["progress"].update(progress)

    consecutive_ratelimit = 0

    with Live(layout, console=_console, refresh_per_second=4, transient=False) as live:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {
                pool.submit(
                    download_and_index_video,
                    vid, channel, batch_no, vtt_dir, index_dir, lang
                ): vid
                for vid in pending
            }

            for future in as_completed(futures):
                result = future.result()
                vid_id = result["video_id"]
                status = result["status"]

                # Update stats
                with _stats_lock:
                    _stats["done"] += 1
                    if status == "ok":
                        _stats["dl_ok"] += 1
                        consecutive_ratelimit = 0
                    elif status == "no_sub":
                        _stats["dl_no_sub"] += 1
                        consecutive_ratelimit = 0
                    elif status == "unavailable":
                        _stats["dl_unavail"] += 1
                        consecutive_ratelimit = 0
                    elif status == "age_restricted":
                        _stats["dl_age"] += 1
                        consecutive_ratelimit = 0
                        # Hook: catat ke log age_restricted
                        try:
                            from cs20_age_engine import hook_log_age_restricted
                            hook_log_age_restricted(
                                config_dir=config_dir,
                                channel=channel,
                                video_id=vid_id,
                                lang=lang,
                            )
                        except Exception:
                            pass
                    elif status == "rate_limited":
                        _stats["dl_ratelimit"] += 1
                        consecutive_ratelimit += 1
                    elif status == "network_error":
                        _stats["dl_network"] += 1
                        consecutive_ratelimit = 0
                    elif status == "parse_error":
                        _stats["dl_error"] += 1
                        consecutive_ratelimit = 0
                    else:
                        _stats["dl_unknown"] += 1
                        consecutive_ratelimit = 0

                # Update status.json
                update_video_status(batch_dir, vid_id, status)

                # Log error jika bukan ok / no_sub
                if status not in ("ok", "no_sub"):
                    append_error_log(
                        error_log, vid_id,
                        result.get("error_type", "unknown"),
                        result.get("error_msg", "")
                    )

                # Update dashboard
                progress.update(task, advance=1)
                layout["dash"].update(
                    _make_dashboard(channel, batch_no, total_batches, batches_per_run)
                )
                layout["progress"].update(progress)
                live.refresh()

                # Rate limit emergency: 10 berturut-turut → pause
                if consecutive_ratelimit >= 10:
                    safe_print(
                        "[red][⚠️] Rate limit berturut-turut terdeteksi! "
                        "Pause download.[/red]"
                    )
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

    # Reload status final
    return load_status(batch_dir)


# ==============================================================================
# ANALYSIS PHASE (reuse fuzzy regex dari engine lama)
# ==============================================================================
def run_analysis_phase(
    batch_dir:  str,
    channel:    str,
    lang:       str,
) -> list:
    """
    Scan semua JSON index di batch_dir/index/ dengan fuzzy regex.
    Return list of result dicts compatible dengan build_html().
    """
    global _stats

    # Set bahasa aktif; scoring didelegasikan ke cs_core (Fase 5/T5.2).
    _load_lang(lang)

    idx_dir    = index_dir_for(batch_dir)
    json_files = sorted(
        f for f in os.listdir(idx_dir) if f.endswith(".json")
    )

    results = []
    with _stats_lock:
        _stats["phase"]      = "analysis"
        _stats["done"]       = 0
        _stats["total"]      = len(json_files)
        _stats["start_time"] = time.time()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(bar_width=_BAR_WIDTH),
        MofNCompleteColumn(),
        TextColumn("[green]{task.percentage:>5.1f}%"),
        TimeRemainingColumn(),
        TextColumn("[yellow]Valid:{task.fields[valid]}"),
        console=_console,
        transient=False,
    )
    task = progress.add_task(
        "Analysis",
        total=len(json_files),
        valid=0,
    )

    with progress:
        for fname in json_files:
            fpath = os.path.join(idx_dir, fname)
            data  = load_json_safe(fpath, None)

            if not data or data.get("status") != "ok":
                with _stats_lock:
                    _stats["done"] += 1
                progress.update(task, advance=1)
                continue

            video_id = data.get("video_id", fname.replace(".json", ""))
            segments = data.get("segments", [])

            result = _analyze_from_segments(video_id, channel, segments)

            results.append(result)

            with _stats_lock:
                _stats["done"] += 1
                if result.get("is_valid"):
                    _stats["an_valid"] += 1
                    _stats["an_hits"]  += len(result.get("hits", []))

            progress.update(
                task, advance=1,
                valid=_stats["an_valid"]
            )

    return results


# Bahasa aktif analisis index (signature lama tak membawa lang).
_CURRENT_LANG = "id"

# Sentinel: modul cs_core tak bisa dimuat -> fallback regex minimal.
_CORE_DEGRADED = False


def _load_lang(lang: str) -> None:
    """Simpan bahasa aktif untuk `_analyze_from_segments` (dipanggil run_analysis_phase)."""
    global _CURRENT_LANG, _CORE_DEGRADED
    _CURRENT_LANG = lang
    try:
        from cs_core.languages import load as _cs_load
        _cs_load(lang)
        _CORE_DEGRADED = False
    except Exception:
        _CORE_DEGRADED = True


def _no_match_base(video_id: str, channel: str, tiers=None) -> dict:
    """Dict base identik engine lama untuk no_match / fallback."""
    return {
        "video_id":    video_id,
        "channel":     channel,
        "status":      "no_match",
        "status_label":"⬜ Tidak Ada Indikasi",
        "hits":        [],
        "score":       0,
        "persentase":  0,
        "tier_counts": {t: 0 for t in (tiers or ("CORE", "TYPO", "SILENT", "CONTEXT", "FP"))},
        "cluster_count": 0,
        "maraton_mins": 0,
        "is_valid":    False,
        "kasta":       "ZONK",
        "kasta_label": "💀 ZONK",
        "html_rows":   "",
    }


def _degraded_result(video_id: str, channel: str, segments: list) -> dict:
    """Fallback minimal tanpa cs_core: regex CORE tunggal (perilaku lama)."""
    base = _no_match_base(video_id, channel)
    if not segments:
        return base
    pat = re.compile(r"cegukan|hiccup|cekukan|jegukan", re.IGNORECASE)
    hits = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        sec  = int(seg.get("sec", 0) or 0)
        if pat.search(text):
            hits.append({
                "sec":   sec,
                "time":  f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}",
                "text":  text,
                "tiers": {"CORE": 1, "TYPO": 0, "SILENT": 0, "CONTEXT": 0, "FP": 0},
                "url":   f"https://youtu.be/{video_id}?t={sec}",
            })
    if not hits:
        return base
    base.update({
        "status":      "analyzed",
        "status_label": f"⚠️ DEGRADED — {len(hits)} hit (cs_core absen)",
        "hits":        hits,
        "score":       len(hits) * 5,
        "persentase":  min(100, len(hits) * 10),
        "tier_counts": {"CORE": len(hits), "TYPO": 0, "SILENT": 0, "CONTEXT": 0, "FP": 0},
        "cluster_count": 1,
        "is_valid":    True,
        "kasta":       "VALID",
        "kasta_label": f"✅ VALID — {len(hits)} hit | DEGRADED",
        "html_rows":   "",
        "degraded":    True,
    })
    return base


def _analyze_from_segments(
    video_id:            str,
    channel:             str,
    segments:            list,
    COMPILED_TIERS:      dict = None,
    ALL_PATTERNS_COMBINED = None,
) -> dict:
    """Analisis segmen index — delegasi `cs_core.scoring` + `compat.to_legacy`.

    Dua arg terakhir dipertahankan demi signature lama (kompatibel pemanggil);
    diabaikan. Mode BASELINE: `hit_span` + `int0` + exact (tanpa fuzzy) ->
    identik engine lama. `degraded=True` hanya bila cs_core absen.
    """
    if _CORE_DEGRADED:
        return _degraded_result(video_id, channel, segments)

    try:
        from cs_core.compat import to_legacy as _cs_to_legacy
        from cs_core.languages import load as _cs_load
        from cs_core.scoring import score_segments as _cs_score

        spec = _cs_load(_CURRENT_LANG)
        result = _cs_score(
            segments, spec,
            video_id=video_id, lang=_CURRENT_LANG,
            cluster_mode="hit_span", dedup_mode="int0",
            enable_fuzzy=False,
        )
        out = _cs_to_legacy(result, mode="BASELINE", engine="IE")
    except Exception:
        # cs_core rusak saat runtime -> fallback minimal sekali, jangan crash.
        return _degraded_result(video_id, channel, segments)

    if result.status == "no_match":
        base = _no_match_base(video_id, channel)
        base["tier_counts"] = dict(out["tier_counts"])
        return base

    out["video_id"] = video_id
    out["channel"] = channel
    out["degraded"] = False
    return out


# ==============================================================================
# HTML BUILD (reuse dari engine lama, dengan badge INDEX MODE)
# ==============================================================================
def build_html_index(
    channel:  str,
    executor: str,
    results:  list,
    lang:     str,
    batch_no: int,
    search_query: str = "",
) -> str:
    """Build HTML report untuk Index Mode. Identik dengan engine lama + badge batch."""
    try:
        from cs20_engine import build_html as _bh
        # Inject batch info ke executor string
        executor_tagged = f"{executor} [INDEX Batch {batch_no:02d}]"
        if search_query:
            executor_tagged += f" [SEARCH: {search_query[:30]}]"
        return _bh(channel, executor_tagged, results, lang)
    except ImportError:
        pass

    # Fallback HTML minimal
    valid  = [r for r in results if r.get("is_valid")]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards  = ""
    for r in sorted(results, key=lambda x: x.get("persentase", 0), reverse=True):
        if r.get("html_rows"):
            cards += f"""
<div style="border:1px solid #1a3a5c;margin:10px 0;padding:10px">
  <a href="https://youtu.be/{r['video_id']}" style="color:#4fc3f7">{r['video_id']}</a>
  <span style="color:#ffc107">{r.get('persentase',0)}%</span>
  <p style="color:#8ab0c8">{r.get('kasta_label','')}</p>
  <table style="width:100%;border-collapse:collapse">{r['html_rows']}</table>
</div>"""
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>CS20 Index Report — @{channel} Batch {batch_no}</title>
<style>body{{background:#080c10;color:#8ab0c8;font-family:monospace}}
.t-link{{color:#00ff88}}.tc{{padding:1px 4px;font-size:.7em}}
.tc.core{{color:#ff3c3c}}</style></head><body>
<h2 style="color:#4fc3f7">INDEX MODE — @{channel} Batch {batch_no:02d}</h2>
<p>Valid: {len(valid)} / {len(results)} | {now_str}</p>
{cards}</body></html>"""


# ==============================================================================
# DISCORD SENDER (wrapper, reuse engine lama)
# ==============================================================================
def send_discord_index(
    webhook_url: str,
    channel:     str,
    executor:    str,
    results:     list,
    html_path:   str,
    batch_no:    int,
    search_query: str = "",
):
    """Kirim laporan Index Mode ke Discord."""
    try:
        from cs20_engine import send_discord as _sd
        executor_tagged = f"{executor} [INDEX Batch {batch_no:02d}]"
        if search_query:
            executor_tagged += f" [SEARCH: {search_query[:30]}]"
        _sd(webhook_url, channel, executor_tagged, results, html_path)
        return
    except ImportError:
        pass

    if not webhook_url or not _req_lib:
        safe_print("[yellow][⚠️] Webhook tidak tersedia. Skip Discord.[/yellow]")
        return

    valid_count = sum(1 for r in results if r.get("is_valid"))
    total_hits  = sum(len(r.get("hits", [])) for r in results)

    title = (
        f"📦 INDEX BATCH {batch_no:02d}"
        + (f" — 🔍 SEARCH: {search_query[:30]}" if search_query else "")
    )

    payload = {"embeds": [{"title": title, "color": 4886754, "fields": [
        {"name": "Target",    "value": f"@{channel}",          "inline": True},
        {"name": "Operator",  "value": executor,                "inline": True},
        {"name": "Hasil",
         "value": f"Valid: {valid_count} | Hits: {total_hits} | Total: {len(results)}",
         "inline": False},
    ]}]}

    try:
        resp = _req_lib.post(webhook_url, json=payload, timeout=30)
        if resp.status_code in (200, 204):
            safe_print("[green][✅] Ringkasan dikirim ke Discord.[/green]")
    except Exception as e:
        safe_print(f"[red][❌] Gagal kirim Discord: {e}[/red]")

    # Attach HTML
    if os.path.exists(html_path):
        size_mb = os.path.getsize(html_path) / (1024 * 1024)
        if size_mb <= 7.5:
            try:
                with open(html_path, "rb") as f:
                    resp2 = _req_lib.post(
                        webhook_url,
                        data={"payload_json": json.dumps(
                            {"content": f"📄 Laporan @{channel} Batch {batch_no:02d}:"}
                        )},
                        files={"file": (os.path.basename(html_path), f, "text/html")},
                        timeout=60,
                    )
                if resp2.status_code in (200, 204):
                    safe_print("[green][✅] File HTML terkirim ke Discord.[/green]")
            except Exception as e:
                safe_print(f"[red][❌] Gagal kirim file: {e}[/red]")
        else:
            safe_print(
                f"[yellow][⚠️] HTML {size_mb:.1f}MB — terlalu besar untuk Discord. "
                f"Disimpan lokal: {html_path}[/yellow]"
            )


# ==============================================================================
# SEARCH MANUAL INTERACTIVE LOOP
# ==============================================================================
def run_manual_search_loop(
    index_dir:   str,
    channel:     str,
    executor:    str,
    webhook_url: str,
    config_dir:  str,
    batch_no:    int,
    lang:        str,
):
    """Interactive loop search manual di terminal."""
    while True:
        safe_print("")
        safe_print(
            Panel(
                "[bold]Contoh penggunaan:[/bold]\n"
                "  [cyan]Kata tunggal  :[/cyan] cegukan\n"
                "  [cyan]Kalimat/phrase:[/cyan] \"lagi minum\"\n"
                "  [cyan]Operator OR  :[/cyan] cegukan OR hiccup\n"
                "  [cyan]Operator AND :[/cyan] cegukan AND minum\n"
                "    [dim](AND = kedua kata ada di video yang sama)[/dim]\n"
                "  [cyan]Kombinasi    :[/cyan] \"cegukan\" AND (\"minum\" OR \"makan\")\n"
                "\n[dim]Ketik 'selesai' untuk kembali[/dim]",
                title="[bold cyan]🔍 SEARCH MANUAL — INDEX MODE[/bold cyan]",
                border_style="cyan",
                width=min(_TERM_WIDTH - 2, 58),
            )
        )

        query = _console.input("  [bold cyan]➤ Keyword:[/bold cyan] ").strip()
        if not query or query.lower() in ("selesai", "exit", "q"):
            safe_print("[dim]  Keluar dari search manual.[/dim]")
            break

        safe_print(f"[dim]  🔍 Mencari: {query} ...[/dim]")
        t0      = time.time()
        results = search_index_batch(index_dir, query, channel)
        elapsed = time.time() - t0

        if not results:
            safe_print(f"[yellow]  Tidak ada hasil untuk: {query}[/yellow]")
        else:
            safe_print(
                f"[green]  ✅ {len(results)} video match ditemukan "
                f"dalam {elapsed:.2f}s[/green]"
            )
            for i, r in enumerate(results[:5]):
                safe_print(
                    f"  [cyan]{r['video_id']}[/cyan] — "
                    f"[yellow]{len(r['hits'])} hit[/yellow] — "
                    f"[dim]{r['kasta_label'][:50]}[/dim]"
                )
            if len(results) > 5:
                safe_print(f"  [dim]... +{len(results)-5} video lainnya di HTML[/dim]")

            # Build HTML & kirim Discord
            html_content = build_html_index(
                channel, executor, results, lang, batch_no, query
            )
            ts        = datetime.now().strftime("%d%m%Y_%H%M%S")
            html_path = os.path.join(
                config_dir,
                f"search_{channel}_b{batch_no:02d}_{ts}.html"
            )
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            send_discord_index(
                webhook_url, channel, executor,
                results, html_path, batch_no, query
            )

            # Hapus HTML lokal jika sudah terkirim dan ukuran aman
            if os.path.exists(html_path):
                if os.path.getsize(html_path) / (1024*1024) <= 7.5:
                    try:
                        os.remove(html_path)
                    except Exception:
                        pass

        # Tanya search lagi?
        lagi = _console.input(
            "\n  [bold]Mau search lagi?[/bold] (y/n): "
        ).strip().lower()
        if lagi not in ("y", "ya", "yes"):
            break


# ==============================================================================
# MAIN PROCESS FUNCTION
# ==============================================================================
def process_index_mode(args):
    global _cleanup_done, _partial_results, _current_error_log, _current_batch_no

    channel        = args.channel
    content_type   = args.content_type
    executor       = args.executor
    lang           = args.lang
    webhook_url    = args.webhook_url
    config_dir     = args.config_dir
    jobs           = min(args.jobs, 3)  # Hard cap 3 worker untuk Index Mode
    total_batches  = args.total_batches
    batches_per_run = args.batches_per_run
    start_batch    = args.start_batch    # 1-based

    cache_root   = detect_cache_root()
    session_dir  = session_dir_for(cache_root, channel)

    # ── Load / init meta ────────────────────────────────────────────
    meta = load_meta(session_dir)

    if not meta:
        # Sesi baru
        total_videos = args.total_videos
        if total_videos <= 0:
            # Coba auto-detect
            safe_print(
                f"[cyan][📊] Menghitung video @{channel}...[/cyan]"
            )
            total_videos = get_playlist_count(channel, content_type)
            if total_videos <= 0:
                safe_print(
                    "[yellow][⚠️] Tidak bisa menghitung otomatis. "
                    "Gunakan --total-videos.[/yellow]"
                )
                return

        videos_per_batch = (total_videos + total_batches - 1) // total_batches

        meta = {
            "channel":          channel,
            "content_type":     content_type,
            "lang":             lang,
            "total_videos":     total_videos,
            "videos_per_batch": videos_per_batch,
            "total_batches":    total_batches,
            "batches_per_run":  batches_per_run,
            "max_workers":      jobs,
            "created_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_updated":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "batches": [
                {
                    "batch_no": i + 1,
                    "start":    i * videos_per_batch + 1,
                    "end":      min((i + 1) * videos_per_batch, total_videos),
                    "status":   "pending",
                }
                for i in range(total_batches)
            ],
        }
        save_meta(session_dir, meta)
        safe_print(
            f"[green][✅] Sesi baru dibuat: "
            f"{total_videos} video → {total_batches} batch "
            f"(~{videos_per_batch} video/batch)[/green]"
        )
    else:
        safe_print(
            f"[green][💾] Sesi existing dimuat untuk @{channel}[/green]"
        )

    # ── SIGINT handler ───────────────────────────────────────────────
    def _on_sigint(sig, frame):
        safe_print("\n[yellow][⚠️] Ctrl+C — menyimpan progress...[/yellow]")
        meta["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_meta(session_dir, meta)
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_sigint)

    # ── Tentukan batch yang akan diproses ────────────────────────────
    pending_batches = [
        b for b in meta["batches"]
        if b["status"] == "pending" and b["batch_no"] >= start_batch
    ][:batches_per_run]

    if not pending_batches:
        safe_print(
            "[green][✅] Semua batch sudah selesai untuk sesi ini![/green]"
        )
        return

    safe_print(
        f"\n[cyan]▶ Memproses {len(pending_batches)} batch: "
        f"{[b['batch_no'] for b in pending_batches]}[/cyan]\n"
    )

    # ── Loop per batch ───────────────────────────────────────────────
    for batch_info in pending_batches:
        batch_no  = batch_info["batch_no"]
        b_start   = batch_info["start"]
        b_end     = batch_info["end"]
        _current_batch_no = batch_no

        bdir      = batch_dir_for(session_dir, batch_no)
        error_log = error_log_path_for(bdir, channel, batch_no)
        _current_error_log = error_log
        init_error_log(error_log, channel, batch_no, lang)

        safe_print(
            Panel(
                f"[white]Batch  : [cyan]{batch_no}[/cyan] / {meta['total_batches']}\n"
                f"Range  : video {b_start} – {b_end}\n"
                f"Jumlah : {b_end - b_start + 1} video\n"
                f"Workers: {jobs}[/white]",
                title=f"[bold cyan]📦 BATCH {batch_no:02d}[/bold cyan]",
                border_style="cyan",
                width=min(_TERM_WIDTH - 2, 50),
            )
        )

        # ── Ambil video IDs ──────────────────────────────────────────
        safe_print(f"[dim][📥] Mengambil video IDs {b_start}–{b_end}...[/dim]")
        video_ids = fetch_video_ids_range(channel, content_type, b_start, b_end)

        if not video_ids:
            safe_print(
                f"[red][❌] Tidak ada video ID di range {b_start}–{b_end}.[/red]"
            )
            batch_info["status"] = "error"
            meta["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_meta(session_dir, meta)
            continue

        safe_print(f"[green]  ✅ {len(video_ids)} video ID ditemukan[/green]")

        # ── FASE 1: DOWNLOAD ─────────────────────────────────────────
        safe_print(f"\n[cyan][⬇️] FASE 1: Download subtitle batch {batch_no}...[/cyan]\n")
        dl_status = run_download_phase(
            video_ids, channel, batch_no, bdir, lang,
            jobs, error_log,
            meta["total_batches"], meta["batches_per_run"],
            config_dir,
        )

        # Error count summary
        err_counts = count_error_log(error_log)
        if err_counts:
            err_str = " | ".join(f"{k}:{v}" for k, v in err_counts.items())
            safe_print(f"[yellow]  ⚠ Error log: {err_str}[/yellow]")

        # ── FASE 2: ANALYSIS ─────────────────────────────────────────
        safe_print(f"\n[green][🔍] FASE 2: Analysis transcript batch {batch_no}...[/green]\n")
        results = run_analysis_phase(bdir, channel, lang)

        valid_count = sum(1 for r in results if r.get("is_valid"))
        safe_print(
            f"[green]  ✅ Analysis selesai: "
            f"{valid_count}/{len(results)} video valid[/green]"
        )

        # ── BUILD HTML & KIRIM DISCORD ───────────────────────────────
        html_content = build_html_index(channel, executor, results, lang, batch_no)
        ts           = datetime.now().strftime("%d%m%Y_%H%M")
        html_path    = os.path.join(
            config_dir,
            f"index_{channel}_b{batch_no:02d}_{ts}.html"
        )
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        send_discord_index(
            webhook_url, channel, executor,
            results, html_path, batch_no
        )

        # Hapus HTML lokal jika aman
        if os.path.exists(html_path):
            if os.path.getsize(html_path) / (1024*1024) <= 7.5:
                try:
                    os.remove(html_path)
                except Exception:
                    pass

        # ── SEARCH MANUAL ────────────────────────────────────────────
        safe_print("")
        do_search = _console.input(
            "[bold]  Mau search manual di index batch ini?[/bold] (y/n): "
        ).strip().lower()

        if do_search in ("y", "ya", "yes"):
            run_manual_search_loop(
                index_dir_for(bdir), channel, executor,
                webhook_url, config_dir, batch_no, lang,
            )

        # ── TRANSISI BATCH ───────────────────────────────────────────
        safe_print("")
        lanjut = _console.input(
            "[bold]  Hapus cache batch ini dan lanjut ke batch berikutnya?[/bold] (y/n): "
        ).strip().lower()

        if lanjut in ("y", "ya", "yes"):
            # Hapus index cache batch ini
            idx_dir = index_dir_for(bdir)
            try:
                shutil.rmtree(idx_dir)
                safe_print(f"[dim]  🗑️  Cache batch {batch_no} dihapus.[/dim]")
            except Exception as e:
                safe_print(f"[yellow]  ⚠ Gagal hapus cache: {e}[/yellow]")

            batch_info["status"] = "done"
        else:
            batch_info["status"] = "paused"
            safe_print(
                f"[yellow]  💾 Batch {batch_no} di-pause. "
                "Jalankan ulang untuk lanjut.[/yellow]"
            )
            meta["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_meta(session_dir, meta)
            break

        meta["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_meta(session_dir, meta)

    safe_print(
        Panel(
            f"[white]Sesi Index Mode untuk @{channel} selesai.[/white]\n"
            f"[dim]Session data: {session_dir}[/dim]",
            title="[bold green]🏁 INDEX MODE SELESAI[/bold green]",
            border_style="green",
        )
    )


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CS20 Index Engine V21")
    parser.add_argument("--channel",          required=True)
    parser.add_argument("--content-type",     default="video")
    parser.add_argument("--executor",         default="Unknown")
    parser.add_argument("--lang",             default="id")
    parser.add_argument("--webhook-url",      default="")
    parser.add_argument("--config-dir",       default=".cs20")
    parser.add_argument("--jobs",             type=int, default=2)
    parser.add_argument("--total-videos",     type=int, default=0)
    parser.add_argument("--total-batches",    type=int, default=10)
    parser.add_argument("--batches-per-run",  type=int, default=2)
    parser.add_argument("--start-batch",      type=int, default=1)

    args = parser.parse_args()
    process_index_mode(args)