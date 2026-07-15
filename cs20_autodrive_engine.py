#!/usr/bin/env python3
# ==============================================================================
# 🚗 AUTO DRIVE ENGINE — Cegukan Seeker V21
# Discovery channel baru otomatis via ytsearch, dedup via history file,
# lalu proses tiap channel baru pakai cs20_engine.py (transcript-based,
# BUKAN chatseeker/yt-dlp live_chat — sengaja dipisah, terlalu berat).
# ==============================================================================

import argparse
import json
import os
import random
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from rich.console import Console
    _console = Console()
    def safe_print(*a, **kw): _console.print(*a, **kw)
except ImportError:
    def safe_print(*a, **kw): print(*a, **kw)


# ==============================================================================
# KONSTANTA & KONFIGURASI
# ==============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_PY  = SCRIPT_DIR / "cs20_engine.py"

# ── Seed query per-bahasa — DITENTUKAN MANUAL, edit langsung di sini. ──
# Maksimal 2 variasi per bahasa (kesepakatan desain — biar gak ribet).
# Kalau cuma mau 1 variasi, cukup isi 1 elemen list-nya.
SEED_QUERIES = {
    "id": ["vtuber indonesia live", "streamer indonesia cegukan"],
    "en": ["vtuber english live stream"],
    "jp": ["Vチューバー 配信"],
    "kr": ["버튜버 방송"],
    "in": ["vtuber hindi live stream"],
    "th": ["vtuber thai live สด"],
}

# Video publik stabil buat ping-check fallback (kalau belum ada
# _last_known_good_video_id sama sekali di sesi ini)
PING_FALLBACK_VIDEO_ID = "dQw4w9WgXcQ"

# ── Circuit breaker signals — HANYA ini yang dihitung sebagai indikasi ──
# rate-limit/block. Status normal (no_chat/unavailable/age_restricted/ok)
# TIDAK masuk hitungan & me-reset counter.
RATE_LIMIT_SIGNALS = {"rate_limited", "auth_required", "network_error"}

BREAKER_THRESHOLD_SEARCH = 3   # consecutive gagal search massal
BREAKER_THRESHOLD_SCAN   = 5   # consecutive gagal scan per-channel

COOLDOWN_PING_DELAY   = (30, 45)     # detik, sebelum ping-check
COOLDOWN_CONFIRMED    = 600          # 10 menit, kalau breaker CONFIRMED
DELAY_ANTAR_CHANNEL   = (5, 10)      # detik, antar channel dalam 1 siklus
DELAY_ANTAR_SIKLUS    = (60, 120)    # detik, antar siklus search

# Mapping preset rentang waktu → flag --dateafter yt-dlp
TIME_RANGE_MAP = {
    "all":   None,
    "1d":    "today-1day",
    "7d":    "today-7days",
    "1m":    "today-1month",
    "1y":    "today-1year",
}


# ==============================================================================
# STATE GLOBAL SESI (di-reset tiap start, TIDAK persisten lintas run)
# ==============================================================================

_last_known_good_video_id = None
_consecutive_search_fail  = 0
_consecutive_scan_fail    = 0
_stats = {
    "cycles":            0,
    "channels_found":     0,
    "channels_skipped":   0,
    "channels_processed": 0,
    "channels_ok":        0,
    "channels_failed":    0,
    "breaker_triggers":   0,
}
_cycle_summary_batch = []   # ringkasan channel per-siklus, dikirim batch ke Discord


# ==============================================================================
# HISTORY FILE (dedup channel, per-bahasa)
# ==============================================================================

def _history_path(config_dir: str, lang: str) -> Path:
    return Path(config_dir) / f"autodrive_history_{lang}.txt"

def load_history(config_dir: str, lang: str) -> set:
    path = _history_path(config_dir, lang)
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def append_history(config_dir: str, lang: str, channel_id: str):
    path = _history_path(config_dir, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(channel_id + "\n")

def clear_history(config_dir: str, lang: str) -> bool:
    path = _history_path(config_dir, lang)
    if path.exists():
        path.unlink()
        return True
    return False


# ==============================================================================
# BREAKER AUDIT LOG
# ==============================================================================

def _log_breaker(config_dir: str, layer: str, reason: str):
    path = Path(config_dir) / "autodrive_breaker_log.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] layer={layer} reason={reason}\n")


# ==============================================================================
# KLASIFIKASI ERROR — SEARCH LAYER (adaptasi dari classifier chatseeker.py)
# ==============================================================================

def _classify_search_error(combined: str) -> str:
    c = combined.lower()
    if "sign in to confirm" in c or "not a bot" in c or "login required" in c:
        return "auth_required"
    if "429" in c or "too many requests" in c or "http error 429" in c:
        return "rate_limited"
    if any(k in c for k in ("timeout", "timed out", "connection reset",
                             "remotedisconnected", "ssl", "broken pipe",
                             "network", "connectionerror", "socket")):
        return "network_error"
    if "no video results" in c or "no results" in c:
        return "no_results"
    return "error"


# ==============================================================================
# STEP 2 — SEARCH MASSAL (ytsearch, flat-playlist, dateafter)
# ==============================================================================

def search_seed(query: str, time_range: str, n_results: int = 50) -> dict:
    """
    Return: {"status": "ok"/"rate_limited"/"network_error"/..., "items": [...]}
    items = list of dict {video_id, channel_id, uploader}
    """
    dateafter = TIME_RANGE_MAP.get(time_range)

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(id)s|%(channel_id)s|%(uploader)s",
        "--no-warnings",
        "--socket-timeout", "30",
    ]
    if dateafter:
        cmd += ["--dateafter", dateafter]
    cmd.append(f"ytsearch{n_results}:{query}")

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        comb = r.stdout + " " + r.stderr

        items = []
        for line in r.stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 3 and parts[0] and parts[1]:
                items.append({
                    "video_id":   parts[0],
                    "channel_id": parts[1],
                    "uploader":   parts[2],
                })

        if items:
            return {"status": "ok", "items": items}

        # Gak ada item — cek apa karena error atau memang no-results
        status = _classify_search_error(comb)
        return {"status": status, "items": []}

    except subprocess.TimeoutExpired:
        return {"status": "network_error", "items": []}
    except FileNotFoundError:
        return {"status": "error", "items": [], "error_msg": "yt-dlp tidak ditemukan"}
    except Exception as e:
        return {"status": "error", "items": [], "error_msg": str(e)[:200]}


# ==============================================================================
# STEP 4 — DEDUP CHANNEL
# ==============================================================================

def extract_new_channels(items: list, seen_history: set, seen_this_run: set) -> list:
    """Unique-kan channel_id dari hasil search, exclude yang sudah di history
    ATAU sudah ketemu di siklus2 sebelumnya dalam run yang sama."""
    new_channels = []
    local_seen = set()
    for item in items:
        cid = item["channel_id"]
        if cid in seen_history or cid in seen_this_run or cid in local_seen:
            continue
        local_seen.add(cid)
        new_channels.append(item)
    return new_channels


# ==============================================================================
# KLASIFIKASI ERROR — CS20_ENGINE.PY SUBPROCESS LAYER
# ==============================================================================
# PENTING: cs20_engine.py TIDAK exit(1) saat rate-limit darurat — dia cuma
# pool.shutdown() + break lalu lanjut sampai akhir fungsi (exit code tetap 0).
# Jadi returncode SENDIRIAN gak bisa dipakai buat deteksi rate-limit di sini.
# Harus grep marker teks pasti yang dicetak handle_rate_limit() di engine.

_ENGINE_RATE_LIMIT_MARKER = "RATE LIMIT TERDETEKSI"

def _classify_engine_subprocess(returncode: int, combined: str) -> str:
    c = combined  # marker case-sensitive, jangan di-lower()

    # Marker pasti dari handle_rate_limit() — ini definisi rate-limit
    # darurat YANG SAMA dengan yang dipakai cs20_engine.py sendiri
    # (10 consecutive_errors), jadi paling akurat, bukan tebakan.
    if _ENGINE_RATE_LIMIT_MARKER in c:
        return "rate_limited"

    cl = c.lower()
    if "sign in to confirm" in cl or "not a bot" in cl:
        return "auth_required"
    if any(k in cl for k in ("timeout", "timed out", "connection reset",
                              "remotedisconnected", "network", "socket")):
        return "network_error"

    if returncode != 0:
        # Crash/exception asli, bukan rate-limit — traceback dsb
        return "error"

    return "ok"


# ==============================================================================
# STEP 6 — PROSES SATU CHANNEL (subprocess ke cs20_engine.py, reuse existing)
# ==============================================================================

def run_channel_scan(channel_id: str, lang: str, limit: int,
                      config_dir: str, checkpoint_dir: str,
                      webhook_url: str, executor: str) -> dict:
    """
    Panggil cs20_engine.py sebagai subprocess — SAMA PERSIS pola yang
    dipakai cs20.sh (run_engine), supaya semua logic scoring/checkpoint/
    error-handling yang sudah ada di engine utama otomatis kepakai tanpa
    duplikasi kode.
    """
    cmd = [
        sys.executable, str(ENGINE_PY),
        "--channel", channel_id,
        "--limit", str(limit),          # limit <= 0 = unlimited (semua arsip live)
        "--jobs", "3",
        "--content-type", "live",       # fokus arsip live (/streams), bukan gado2
        "--executor", executor,
        "--mode", "pantau",
        "--start-from", "0",
        "--checkpoint-dir", checkpoint_dir,
        "--config-dir", config_dir,
        "--webhook-url", webhook_url,
        "--lang", lang,
    ]
    # Timeout scan lebih longgar kalau unlimited — bisa banyak video sekali jalan
    scan_timeout = 5400 if limit <= 0 else 1800
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=scan_timeout)
        comb = r.stdout + " " + r.stderr

        # ── Relay baris penting dari child ke terminal Auto Drive ──
        # (sebelumnya di-swallow total — gagal kirim Discord jadi senyap)
        _relay_child_output(comb)

        status = _classify_engine_subprocess(r.returncode, comb)
        if status == "ok":
            return {"status": "ok", "channel_id": channel_id}

        return {"status": status, "channel_id": channel_id,
                "error_msg": r.stderr.strip()[:300]}

    except subprocess.TimeoutExpired:
        return {"status": "network_error", "channel_id": channel_id,
                "error_msg": f"Timeout scan channel (>{scan_timeout//60} menit)"}
    except Exception as e:
        return {"status": "error", "channel_id": channel_id, "error_msg": str(e)[:200]}


def _relay_child_output(combined: str):
    """Tampilin baris penting dari output cs20_engine.py yang tadinya
    di-swallow total oleh capture_output — khususnya status kirim Discord
    (sukses/403/429/exception) biar gak senyap kalau gagal."""
    keywords = (
        "Ringkasan terkirim", "403 Forbidden", "429", "rate-limited",
        "Gagal kirim embed", "Webhook URL tidak ditemukan",
        "File HTML berhasil dikirim", "terlalu besar",
    )
    for line in combined.splitlines():
        s = line.strip()
        if s and any(k in s for k in keywords):
            safe_print(f"    [dim]│ {s}[/dim]")


# ==============================================================================
# PING-CHECK — verifikasi sebelum declare rate-limit CONFIRMED
# ==============================================================================

def ping_check() -> bool:
    """
    Re-fetch transcript video yang TERAKHIR TERBUKTI SUKSES di sesi ini
    (_last_known_good_video_id). Kalau belum ada sama sekali, fallback ke
    video default. Return True kalau koneksi/akses masih normal.
    """
    global _last_known_good_video_id
    video_id = _last_known_good_video_id or PING_FALLBACK_VIDEO_ID

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        api.fetch(video_id, languages=["en", "id", "ja", "ko"])
        return True
    except Exception as e:
        # TranscriptsDisabled/NoTranscriptFound = video-nya emang gak punya
        # transkrip, itu BUKAN indikasi rate-limit — tetap dianggap "sehat"
        etype = type(e).__name__
        if etype in ("NoTranscriptFound", "TranscriptsDisabled", "VideoUnavailable"):
            return True
        return False


# ==============================================================================
# CIRCUIT BREAKER HANDLER
# ==============================================================================

def handle_breaker_trigger(layer: str, config_dir: str, webhook_url: str) -> bool:
    """
    Return True kalau CONFIRMED rate-limit (caller harus cooldown besar),
    False kalau ternyata false-alarm (counter di-reset, lanjut normal).
    """
    global _consecutive_search_fail, _consecutive_scan_fail

    safe_print(f"[yellow][⚠️] Circuit breaker layer={layer} tercapai. "
               f"Verifikasi via ping-check...[/yellow]")

    delay = random.uniform(*COOLDOWN_PING_DELAY)
    time.sleep(delay)

    if ping_check():
        safe_print("[green][✓] Ping-check sukses — false alarm, lanjut normal.[/green]")
        _consecutive_search_fail = 0
        _consecutive_scan_fail   = 0
        return False

    safe_print("[red][✗] Ping-check GAGAL — rate-limit CONFIRMED.[/red]")
    _log_breaker(config_dir, layer, "confirmed_after_ping_check")
    _stats["breaker_triggers"] += 1
    _send_breaker_notice(webhook_url, layer)

    safe_print(f"[red]  Cooldown {COOLDOWN_CONFIRMED}s sebelum lanjut siklus berikutnya...[/red]")
    time.sleep(COOLDOWN_CONFIRMED)

    _consecutive_search_fail = 0
    _consecutive_scan_fail   = 0
    return True


def _send_breaker_notice(webhook_url: str, layer: str):
    if not webhook_url:
        return
    payload = {
        "embeds": [{
            "title": "⚠️ AUTO DRIVE — RATE LIMIT CONFIRMED",
            "color": 16711680,
            "description": (
                f"Circuit breaker layer **{layer}** ter-trigger dan "
                f"terkonfirmasi lewat ping-check.\n\n"
                f"Cooldown {COOLDOWN_CONFIRMED // 60} menit sebelum lanjut."
            )
        }]
    }
    try:
        req = urllib.request.Request(
            webhook_url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def _send_cycle_summary(webhook_url: str, lang: str, cycle_no: int):
    if not webhook_url or not _cycle_summary_batch:
        return
    entries = [f"- `{c['channel_id']}` → {c['status']}" for c in _cycle_summary_batch]
    lines = "\n".join(entries)
    header = f"Channel baru diproses: {len(_cycle_summary_batch)}\n\n"
    # Discord description limit 4096 — potong list kalau kepanjangan, sisanya diringkas
    budget = 3900 - len(header)
    if len(lines) > budget:
        kept, used = [], 0
        for e in entries:
            if used + len(e) + 1 > budget:
                break
            kept.append(e)
            used += len(e) + 1
        lines = "\n".join(kept) + f"\n… +{len(entries) - len(kept)} channel lainnya"
    payload = {
        "embeds": [{
            "title": f"🚗 Auto Drive — Siklus #{cycle_no} Selesai ({lang})",
            "color": 3066993,
            "description": header + lines
        }]
    }
    try:
        req = urllib.request.Request(
            webhook_url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


# ==============================================================================
# MAIN LOOP
# ==============================================================================

def run_autodrive(lang: str, time_range: str, limit_per_channel: int,
                   max_cycles: int, config_dir: str, checkpoint_dir: str,
                   webhook_url: str, executor: str, custom_queries: list = None):
    global _last_known_good_video_id, _consecutive_search_fail, _consecutive_scan_fail
    global _cycle_summary_batch

    # Query custom SESI INI SAJA — tidak pernah nulis balik ke SEED_QUERIES.
    # Kalau dikasih, override total (bukan nambah) buat sesi berjalan.
    if custom_queries:
        queries = custom_queries
        safe_print(f"[cyan][ℹ️] Pakai custom query sesi ini (tidak disimpan): "
                    f"{', '.join(queries)}[/cyan]")
    else:
        queries = SEED_QUERIES.get(lang)

    if not queries:
        safe_print(f"[red]Belum ada seed query untuk bahasa '{lang}'. "
                    f"Edit SEED_QUERIES di cs20_autodrive_engine.py, atau isi custom query dari menu.[/red]")
        return

    history          = load_history(config_dir, lang)
    seen_this_run    = set()
    no_new_streak    = 0   # siklus berturut-turut tanpa channel baru
    cycle_no         = 0

    def _on_sigint(sig, frame):
        safe_print("\n[yellow][⚠️] Ctrl+C diterima — menghentikan Auto Drive...[/yellow]")
        safe_print("[green][✓] History AMAN — sudah ditulis real-time per-channel, "
                   "bukan cuma di akhir sesi. Channel yang belum sempat diproses "
                   "TIDAK tercatat di history, jadi otomatis akan dicoba lagi "
                   "di sesi berikutnya (bukan ke-skip permanen).[/green]")
        safe_print(f"[dim]Total siklus: {_stats['cycles']} | "
                    f"Channel diproses: {_stats['channels_processed']}[/dim]")
        sys.exit(0)

    import signal
    signal.signal(signal.SIGINT, _on_sigint)

    while True:
        cycle_no += 1
        _stats["cycles"] += 1
        _cycle_summary_batch = []

        query = queries[(cycle_no - 1) % len(queries)]  # rotate kalau 2 variasi
        safe_print(f"\n[bold cyan]═══ SIKLUS #{cycle_no} — query: \"{query}\" ═══[/bold cyan]")

        # ── STEP 2: Search massal ──────────────────────────────────
        result = search_seed(query, time_range)

        if result["status"] != "ok":
            if result["status"] in RATE_LIMIT_SIGNALS:
                _consecutive_search_fail += 1
                safe_print(f"[yellow]Search gagal ({result['status']}), "
                           f"consecutive={_consecutive_search_fail}[/yellow]")
                if _consecutive_search_fail >= BREAKER_THRESHOLD_SEARCH:
                    handle_breaker_trigger("search", config_dir, webhook_url)
            else:
                safe_print(f"[dim]Search: {result['status']} (bukan sinyal rate-limit)[/dim]")
            # Baik rate-limit maupun error lain — skip ke siklus berikutnya
            time.sleep(random.uniform(*DELAY_ANTAR_SIKLUS))
            if max_cycles and cycle_no >= max_cycles:
                break
            continue

        _consecutive_search_fail = 0  # search sukses → reset

        # ── STEP 4: Ekstraksi & dedup channel ──────────────────────
        new_channels = extract_new_channels(result["items"], history, seen_this_run)
        _stats["channels_found"]   += len(result["items"])
        _stats["channels_skipped"] += len(result["items"]) - len(new_channels)

        if not new_channels:
            no_new_streak += 1
            safe_print(f"[dim]Semua channel di hasil search sudah pernah di-scan. "
                       f"(streak: {no_new_streak})[/dim]")
            if no_new_streak >= 2:
                safe_print("[yellow]2 siklus berturut tanpa channel baru — "
                           "info aja, BUKAN circuit breaker, lanjut normal.[/yellow]")
            time.sleep(random.uniform(*DELAY_ANTAR_SIKLUS))
            if max_cycles and cycle_no >= max_cycles:
                break
            continue

        no_new_streak = 0
        safe_print(f"[green]{len(new_channels)} channel baru ditemukan.[/green]")

        # ── STEP 6-7: Proses tiap channel baru ─────────────────────
        for item in new_channels:
            cid = item["channel_id"]
            seen_this_run.add(cid)

            safe_print(f"  [cyan]→ Scan channel {cid} ({item['uploader']})...[/cyan]")
            scan_result = run_channel_scan(
                cid, lang, limit_per_channel,
                config_dir, checkpoint_dir, webhook_url, executor
            )

            # Tulis history SEGERA — biar aman kalau ke-interrupt
            append_history(config_dir, lang, cid)
            history.add(cid)

            _stats["channels_processed"] += 1
            _cycle_summary_batch.append({"channel_id": cid, "status": scan_result["status"]})

            status = scan_result["status"]
            if status == "ok":
                _stats["channels_ok"] += 1
                _consecutive_scan_fail = 0
                safe_print(f"    [green]✓ selesai, laporan terkirim.[/green]")
                # Simpan sebagai last-known-good buat ping-check nanti
                if item["video_id"]:
                    _last_known_good_video_id = item["video_id"]
            elif status in RATE_LIMIT_SIGNALS:
                _stats["channels_failed"] += 1
                _consecutive_scan_fail += 1
                safe_print(f"    [yellow]status={status}, "
                           f"consecutive={_consecutive_scan_fail}[/yellow]")
                if _consecutive_scan_fail >= BREAKER_THRESHOLD_SCAN:
                    confirmed = handle_breaker_trigger("scan", config_dir, webhook_url)
                    if confirmed:
                        # SENGAJA: channel sisa di `new_channels` yang belum
                        # sempat diproses TIDAK ditulis ke history (karena
                        # belum pernah benar-benar di-scan). Ini benar secara
                        # desain — mereka akan otomatis masuk antrian lagi di
                        # siklus berikutnya (kalau query yang sama nemu channel
                        # yang sama lagi), BUKAN ke-skip permanen. Cuma channel
                        # yang di dalam loop ini SUDAH diproses (baris di atas)
                        # yang tercatat ke history.
                        break  # keluar dari loop channel, lanjut ke siklus baru
            else:
                # status normal lain (no_chat/unavailable/dll) — reset counter
                _stats["channels_failed"] += 1
                _consecutive_scan_fail = 0
                safe_print(f"    [dim]status={status}[/dim]")

            time.sleep(random.uniform(*DELAY_ANTAR_CHANNEL))

        # ── STEP 8: Ringkasan batch akhir siklus ───────────────────
        _send_cycle_summary(webhook_url, lang, cycle_no)
        safe_print(f"[dim]Siklus #{cycle_no} selesai. Jeda sebelum siklus berikutnya...[/dim]")

        if max_cycles and cycle_no >= max_cycles:
            safe_print(f"[green]Max siklus ({max_cycles}) tercapai. Berhenti.[/green]")
            break

        time.sleep(random.uniform(*DELAY_ANTAR_SIKLUS))

    safe_print(f"\n[bold]═══ AUTO DRIVE SELESAI ═══[/bold]")
    safe_print(f"Siklus: {_stats['cycles']} | "
               f"Channel baru: {_stats['channels_processed']} | "
               f"OK: {_stats['channels_ok']} | Gagal: {_stats['channels_failed']} | "
               f"Breaker trigger: {_stats['breaker_triggers']}")


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Auto Drive — channel discovery otomatis")
    parser.add_argument("--lang", required=True, choices=list(SEED_QUERIES.keys()))
    parser.add_argument("--time-range", default="all", choices=list(TIME_RANGE_MAP.keys()))
    parser.add_argument("--limit-per-channel", type=int, default=10)
    parser.add_argument("--max-cycles", type=int, default=0)  # 0 = tanpa batas
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--executor", default="autodrive")
    parser.add_argument("--clear-history", action="store_true")
    parser.add_argument("--custom-query", default="",
                         help="Query custom, pisah pakai '|' kalau lebih dari 1. "
                              "SESI INI SAJA, tidak ditulis ke SEED_QUERIES.")
    args = parser.parse_args()

    if args.clear_history:
        cleared = clear_history(args.config_dir, args.lang)
        safe_print(f"[green]History {'dihapus' if cleared else 'sudah kosong'}.[/green]")
        return

    custom_queries = [q.strip() for q in args.custom_query.split("|") if q.strip()] or None

    run_autodrive(
        lang=args.lang,
        time_range=args.time_range,
        limit_per_channel=args.limit_per_channel,
        max_cycles=args.max_cycles,
        config_dir=args.config_dir,
        checkpoint_dir=args.checkpoint_dir,
        webhook_url=args.webhook_url,
        executor=args.executor,
        custom_queries=custom_queries,
    )


if __name__ == "__main__":
    main()
