"""HTML rows minimal untuk Fase 1.

P5: highlight dibangun dari match offset sekali jalan (bukan `pat.sub`
bertingkat), jadi TIDAK ada `<span>` di dalam `<span>`. `build_html` penuh
menyusul Fase 6.
"""

from __future__ import annotations

import html as _html
import json as _json
import os as _os
import time as _time
import urllib.request as _urlreq
from datetime import datetime as _datetime

from . import config as _config

__all__ = [
    "build_html",
    "build_html_rows",
    "send_discord",
    "escape_html",
    "highlight_matches",
]

_TIER_CLASS = {"CORE": "core", "TYPO": "typo", "SILENT": "silent", "CONTEXT": "ctx"}

# ── Batas Discord: field value 1024 char, description 4096, total embed 6000 ──
_DISCORD_FIELD_LIMIT = 1000   # sisa buffer dari 1024
_DISCORD_DESC_LIMIT = 4000    # sisa buffer dari 4096
_DISCORD_FILE_MAX_MB = 7.5

_LANG_LABELS = {
    "id": ("id", "INDONESIA"),
    "en": ("en", "ENGLISH"),
    "jp": ("ja", "JAPANESE"),
    "kr": ("ko", "KOREAN"),
    "in": ("hi", "HINDI / INDIA"),
}

# Kanal ber-ID mentah (bukan @handle). Duck-typed: engine lama punya
# `_is_raw_channel_id`; di sini dicek pola UC + 22 char (tak import engine).
_RAW_ID_CHANNEL_RE = None


def _is_raw_channel_id(channel: str) -> bool:
    import re

    return bool(re.fullmatch(r"UC[\w-]{22}", channel or ""))


def channel_label(channel: str, display_name: str = "") -> str:
    """Label display kanal — `@handle`, `@name`, atau `channel/UCxxx`."""
    if _is_raw_channel_id(channel):
        if display_name:
            return f"@{display_name}"
        return f"channel/{channel}"
    return f"@{channel}"


def escape_html(text: str) -> str:
    return _html.escape(text or "", quote=False)


def _dominant_class(tiers: dict) -> str:
    if tiers.get("SILENT", 0):
        return "silent"
    if tiers.get("CORE", 0):
        return "core"
    if tiers.get("TYPO", 0):
        return "typo"
    if tiers.get("CONTEXT", 0):
        return "ctx"
    return ""


def _tier_strip(tiers: dict) -> str:
    strip = ""
    if tiers.get("CORE", 0):
        strip += "<span class='tc core'>CORE</span> "
    if tiers.get("TYPO", 0):
        strip += "<span class='tc typo'>TYPO</span> "
    if tiers.get("SILENT", 0):
        strip += "<span class='tc silent'>SILENT</span> "
    if tiers.get("CONTEXT", 0):
        strip += "<span class='tc ctx'>CTX</span> "
    return strip


def _collect_spans(text: str, spec) -> list[tuple[int, int, str]]:
    """Kumpulkan (start, end, cls) dari match per pattern. Tanpa sub bertingkat."""
    spans: list[tuple[int, int, str]] = []
    if not spec:
        return spans
    for core in getattr(spec, "cores", ()) or ():
        cls = _TIER_CLASS.get(core.tier, "")
        if not cls:
            continue
        for pat in core.regexes or ():
            for m in pat.finditer(text):
                if m.start() == m.end():
                    continue
                spans.append((m.start(), m.end(), cls))
    return spans


def _merge_spans(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Gabung span overlap/tumpang tindih; kelas menang = span terpanjang/awal."""
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[list] = []
    for s, e, cls in spans:
        if merged and s < merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1][1] = e
            continue
        merged.append([s, e, cls])
    return [(s, e, c) for s, e, c in merged]


def highlight_matches(text: str, spec=None, spec_or_result=None) -> str:
    """Highlight satu lapis dari offset match. Tidak ada nested span."""
    spec = spec if spec is not None else spec_or_result
    spans = _merge_spans(_collect_spans(text, spec))
    if not spans:
        return escape_html(text)
    out = []
    cursor = 0
    for s, e, cls in spans:
        out.append(escape_html(text[cursor:s]))
        out.append(f"<span class='hl {cls}'>{escape_html(text[s:e])}</span>")
        cursor = e
    out.append(escape_html(text[cursor:]))
    return "".join(out)


def build_html_rows(result, mode=None, spec=None, engine: str = "E") -> str:
    """Bangun `<tr>` per hit. `result` boleh dict lama atau AnalysisResult.

    P5/R1: mode BASELINE + engine != "E" -> TANPA highlight inline, meniru
    IE/AE lama (hanya tier_strip). Mode IMPROVED selalu highlight span bersih.
    """
    if mode is None:
        mode = _config.CompatMode.from_env()
    do_highlight = (mode is not _config.CompatMode.BASELINE) or (engine == "E")

    # Ambil lang spec bila result membawa `lang` tapi tak ada spec eksplisit.
    if spec is None and hasattr(result, "lang") and result.lang:
        try:
            from .languages import load as _load

            spec = _load(result.lang)
        except Exception:
            spec = None

    hits = result["hits"] if isinstance(result, dict) else result.hits

    rows = ""
    for hit in hits:
        if isinstance(hit, dict):
            h_text = hit.get("text", "")
            h_tiers = hit.get("tiers", {})
            h_url = hit.get("url", "")
            h_time = hit.get("time", "")
        else:
            h_text = hit.text
            h_tiers = hit.tiers
            h_url = hit.url
            h_time = hit.time

        hl_class = _dominant_class(h_tiers)
        highlighted = highlight_matches(h_text, spec) if do_highlight else escape_html(h_text)
        tier_strip = _tier_strip(h_tiers)

        rows += (
            "<tr>"
            f"<td><a href='{_html.escape(h_url, quote=True)}' target='_blank' class='t-link'>"
            f"[{escape_html(h_time)}]</a></td>"
            f"<td>{tier_strip}{highlighted}</td>"
            "</tr>\n"
        )
    return rows


# ==============================================================================
# FULL HTML REPORT (Fase 6/T6.1-T6.2) — dipindah dari cs20_engine.build_html
# ==============================================================================
_CARD_CLASS = {
    "GOD_MODE": "god",
    "VALID_HIGH": "valid-high",
    "SILENT": "silent",
    "VALID": "valid",
    "LOW": "low",
}

_REPORT_CSS = """* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #080c10;
  color: #8ab0c8;
  font-family: 'Courier New', monospace;
  min-height: 100vh;
}

/* ── HEADER ─────────────────────────────────────────────────── */
.header {
  background: linear-gradient(135deg, #080c10 0%, #0d1520 100%);
  border-bottom: 1px solid #1a3a5c;
  padding: 20px 28px;
}
.header-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}
.header h1 {
  color: #4fc3f7;
  font-size: 1.0em;
  letter-spacing: 3px;
  text-transform: uppercase;
  text-shadow: 0 0 12px #4fc3f755;
}
.header h1 span { color: #fff; }
.op-tag {
  background: #ff3c3c22;
  border: 1px solid #ff3c3c;
  color: #ff3c3c;
  font-size: 0.65em;
  padding: 4px 14px;
  letter-spacing: 2px;
  animation: blink 1.5s step-end infinite;
}
@keyframes blink { 50% { opacity: 0.3; } }
.header-meta {
  display: flex;
  gap: 24px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.meta-item { font-size: 0.68em; }
.meta-item .key { color: #1a3a5c; text-transform: uppercase; letter-spacing: 1px; }
.meta-item .val { color: #4fc3f7; margin-left: 6px; }

/* ── CONTENT ─────────────────────────────────────────────────── */
.content {
  padding: 24px 28px;
  max-width: 980px;
  margin: 0 auto;
}

/* ── STATS GRID ──────────────────────────────────────────────── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}
.stat-card {
  background: #0d1520;
  border: 1px solid #1a3a5c;
  padding: 14px;
  text-align: center;
  position: relative;
  overflow: hidden;
}
.stat-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: #4fc3f7;
}
.stat-card.red::before  { background: #ff3c3c; }
.stat-card.green::before { background: #00ff88; }
.stat-card.yellow::before { background: #ffc107; }
.stat-card .n { font-size: 1.8em; font-weight: bold; color: #4fc3f7; }
.stat-card.red .n    { color: #ff3c3c; }
.stat-card.green .n  { color: #00ff88; }
.stat-card.yellow .n { color: #ffc107; }
.stat-card .l {
  font-size: 0.62em;
  color: #1a4a6c;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-top: 5px;
}

/* ── LANG BADGE ──────────────────────────────────────────────── */
.lang-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #0d1520;
  border: 1px solid #4fc3f755;
  color: #4fc3f7;
  font-size: 0.7em;
  padding: 5px 14px;
  margin-bottom: 20px;
  letter-spacing: 1px;
}
.lang-badge .dot {
  width: 6px; height: 6px;
  background: #4fc3f7;
  border-radius: 50%;
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%,100% { opacity:1; transform:scale(1); }
  50%      { opacity:0.4; transform:scale(0.7); }
}

/* ── SECTION HEADING ─────────────────────────────────────────── */
.section-head {
  font-size: 0.68em;
  color: #1a3a5c;
  text-transform: uppercase;
  letter-spacing: 2px;
  padding: 4px 0;
  border-bottom: 1px solid #1a3a5c;
  margin-bottom: 16px;
}
.section-head span { color: #4fc3f7; }

/* ── CARDS ───────────────────────────────────────────────────── */
.card {
  background: #0a0f18;
  border: 1px solid #1a3a5c;
  margin-bottom: 14px;
  position: relative;
}
.card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: #4fc3f7;
}
.card.god::before        { background: linear-gradient(180deg, #ffd700, #ff8c00); }
.card.valid-high::before { background: #ff3c3c; }
.card.silent::before     { background: #a020f0; }
.card.valid::before      { background: #00ff88; }
.card.low::before        { background: #445566; }

.card-head {
  padding: 10px 16px 10px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  border-bottom: 1px solid #0f1e2e;
}
.vid-id {
  color: #4fc3f7;
  font-weight: bold;
  font-size: 0.88em;
  text-decoration: none;
}
.vid-id:hover { text-shadow: 0 0 8px #4fc3f7; }
.confidence {
  margin-left: auto;
  font-size: 0.68em;
  color: #445566;
}
.pct {
  font-size: 1.5em;
  font-weight: bold;
  color: #4fc3f7;
}
.pct.high { color: #ff3c3c; }
.pct.mid  { color: #ffc107; }
.card-status {
  font-size: 0.70em;
  color: #4fc3f788;
  width: 100%;
  padding: 4px 0 2px 0;
}

/* ── TIER STRIP ──────────────────────────────────────────────── */
.tier-strip {
  padding: 6px 16px 6px 20px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  background: #060a10;
  border-bottom: 1px solid #0f1e2e;
}
.tc {
  font-size: 0.65em;
  padding: 2px 8px;
  font-weight: bold;
  border-left: 2px solid;
}
.tc.core   { color: #ff3c3c; border-color: #ff3c3c; }
.tc.typo   { color: #ffa050; border-color: #ffa050; }
.tc.silent { color: #c060ff; border-color: #c060ff; }
.tc.ctx    { color: #4fc3f7; border-color: #4fc3f7; }
.tc.fp     { color: #556677; border-color: #556677; }

/* ── TABLE ───────────────────────────────────────────────────── */
table { width: 100%; border-collapse: collapse; }
th {
  padding: 7px 16px 7px 20px;
  font-size: 0.65em;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #1a3a5c;
  border-bottom: 1px solid #0f1e2e;
  text-align: left;
  background: #060a10;
}
td {
  padding: 6px 16px 6px 20px;
  font-size: 0.80em;
  border-bottom: 1px solid #0a1018;
  color: #8ab0c8;
  vertical-align: top;
  line-height: 1.5;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #0d1520; color: #c0d8e8; }
.t-link {
  color: #00ff88;
  text-decoration: none;
  font-weight: bold;
  font-size: 0.85em;
  white-space: nowrap;
}
.t-link:hover { text-shadow: 0 0 6px #00ff88; }

/* ── INLINE HIGHLIGHT ────────────────────────────────────────── */
.hl { padding: 1px 3px; font-weight: bold; border-radius: 1px; }
.hl.core   { background: #ff3c3c33; color: #ff8080; border-bottom: 1px solid #ff3c3c; }
.hl.typo   { background: #ffa05033; color: #ffc080; border-bottom: 1px solid #ffa050; }
.hl.silent { background: #a020f033; color: #d080ff; border-bottom: 1px solid #a020f0; }
.hl.ctx    { background: #4fc3f722; color: #90d8ff; border-bottom: 1px solid #4fc3f7; }

/* ── NO-TRANSCRIPT ───────────────────────────────────────────── */
.no-trans-section { margin-top: 28px; }
.no-trans-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.no-trans-grid a {
  color: #1a3a5c;
  font-size: 0.72em;
  border: 1px solid #1a3a5c;
  padding: 3px 10px;
  text-decoration: none;
}
.no-trans-grid a:hover { color: #4fc3f7; border-color: #4fc3f7; }

/* ── FOOTER ──────────────────────────────────────────────────── */
footer {
  text-align: center;
  color: #1a3a5c;
  font-size: 0.65em;
  padding: 24px;
  border-top: 1px solid #0f1e2e;
  margin-top: 28px;
}"""


def _card_class(kasta: str) -> str:
    return _CARD_CLASS.get(kasta, "")


def _pct_class(pct: int) -> str:
    if pct >= 75:
        return "high"
    if pct >= 40:
        return "mid"
    return ""


def _tier_strip_counts(tier_counts: dict) -> str:
    parts = []
    if tier_counts.get("CORE", 0):
        parts.append(f"<span class='tc core'>CORE &times;{tier_counts['CORE']}</span>")
    if tier_counts.get("TYPO", 0):
        parts.append(f"<span class='tc typo'>TYPO &times;{tier_counts['TYPO']}</span>")
    if tier_counts.get("SILENT", 0):
        parts.append(f"<span class='tc silent'>SILENT &times;{tier_counts['SILENT']}</span>")
    if tier_counts.get("CONTEXT", 0):
        parts.append(f"<span class='tc ctx'>CTX &times;{tier_counts['CONTEXT']}</span>")
    if tier_counts.get("FP", 0):
        parts.append(f"<span class='tc fp'>FP &times;{tier_counts['FP']}</span>")
    return " ".join(parts)


def build_html(channel: str, executor: str, results: list, lang: str = "id",
               meta: dict | None = None) -> str:
    """Bangun HTML laporan penuh. Semua nilai dinamis di-escape.

    `meta` opsional: `{"display_name": ..., "title_badge": ...}`. Default:
    tidak ada badge (engine E lama).
    """
    meta = meta or {}
    display_name = meta.get("display_name") or ""

    valid_results = [r for r in results if r.get("is_valid")]
    no_trans = [r for r in results
                if r["status"] in ("no_transcript", "disabled", "unavailable")]
    analyzed = [r for r in results if r["status"] == "analyzed"]

    sorted_results = sorted(analyzed, key=lambda x: x["persentase"], reverse=True)
    now = _datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    html_lang, lang_name = _LANG_LABELS.get(lang, ("id", "INDONESIA"))
    total_hits = sum(len(r.get("hits", [])) for r in results)

    ch_label = channel_label(channel, display_name)

    # ── CARDS HTML ────────────────────────────────────────────────
    cards_html = ""
    for r in sorted_results:
        if not r.get("html_rows"):
            continue
        vid = escape_html(str(r.get("video_id", "")))
        cc = _card_class(r.get("kasta", ""))
        pc = _pct_class(r.get("persentase", 0))
        ts = _tier_strip_counts(r.get("tier_counts", {}))
        cards_html += f"""
    <div class="card {cc}">
      <div class="card-head">
        <a class="vid-id" href="https://youtu.be/{vid}" target="_blank">&#9889; {vid}</a>
        <div class="confidence">
          <span class="pct {pc}">{int(r.get('persentase', 0))}%</span> CONFIDENCE
        </div>
        <div class="card-status">{escape_html(r.get('kasta_label', ''))}</div>
      </div>
      <div class="tier-strip">{ts}</div>
      <table>
        <tr><th>TIMESTAMP</th><th>TRANSCRIPT EVIDENCE</th></tr>
        {r['html_rows']}
      </table>
    </div>"""

    # ── NO-TRANSCRIPT GRID ────────────────────────────────────────
    no_trans_links = "".join(
        f"<a href='https://youtu.be/{_html.escape(str(r.get('video_id', '')), quote=True)}'"
        f" target='_blank'>{escape_html(str(r.get('video_id', '')))}</a>"
        for r in no_trans
    )

    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CS20 Intel Report — {escape_html(ch_label)}</title>
<style>
{_REPORT_CSS}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <h1>CEGUKAN SEEKER &mdash; <span>INTEL REPORT</span> V20</h1>
    <div class="op-tag">&#9679; REPORT SELESAI</div>
  </div>
  <div class="header-meta">
    <div class="meta-item"><span class="key">TARGET</span><span class="val">{escape_html(ch_label)}</span></div>
    <div class="meta-item"><span class="key">OPERATOR</span><span class="val">{escape_html(executor)}</span></div>
    <div class="meta-item"><span class="key">ENGINE LANG</span><span class="val">{escape_html(lang_name)}</span></div>
    <div class="meta-item"><span class="key">TIMESTAMP</span><span class="val">{now_str}</span></div>
  </div>
</div>

<div class="content">
  <div class="lang-badge">
    <span class="dot"></span>
    ENGINE AKTIF &mdash; BAHASA {escape_html(lang_name)}
  </div>

  <div class="stats-grid">
    <div class="stat-card red">
      <div class="n">{len(valid_results)}</div>
      <div class="l">CONFIRMED HITS</div>
    </div>
    <div class="stat-card">
      <div class="n">{len(results)}</div>
      <div class="l">TOTAL ANALYZED</div>
    </div>
    <div class="stat-card yellow">
      <div class="n">{len(no_trans)}</div>
      <div class="l">NO TRANSCRIPT</div>
    </div>
    <div class="stat-card green">
      <div class="n">{total_hits}</div>
      <div class="l">TOTAL MOMENTS</div>
    </div>
  </div>

  <div class="section-head">CONFIRMED &mdash; <span>{len(valid_results)} VIDEO TERDETEKSI</span></div>
  {cards_html}

  <div class="no-trans-section">
    <div class="section-head">NO TRANSCRIPT &mdash; <span>{len(no_trans)} VIDEO EXCLUDED</span></div>
    <div class="no-trans-grid">
      {no_trans_links}
    </div>
  </div>

  <footer>CS20 Intel Report V20.0 | Fuzzy Regex Engine | {date_str}</footer>
</div>

</body>
</html>"""


# ==============================================================================
# DISCORD WEBHOOK (Fase 6/T6.1) — dipindah dari cs20_engine.send_discord
# ==============================================================================
def _trunc(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 20].rstrip() + "\n… (dipotong)"


def _kasta_global(results: list, valid_results: list) -> tuple[str, int]:
    has_god = any(r.get("kasta") == "GOD_MODE" for r in results)
    has_valid_high = any(r.get("kasta") == "VALID_HIGH" for r in results)
    if has_god or len(valid_results) >= 3:
        return "👑 [GOD MODE] ANOMALI MEDIS TERDETEKSI!", 16761035
    if has_valid_high or valid_results:
        return "🔥 [HIGH HYPE] INDIKASI KUAT DITEMUKAN!", 2359050
    if results:
        return "📋 [ALERT] INDIKASI LEMAH / FALSE ALARM", 16744192
    return "💀 [ZONK] TARGET DIET CEGUKAN!", 8421504


def _log(msg: str) -> None:
    """Output via engine lama (`safe_print`) bila ada; else stdout."""
    try:
        from cs20_engine import safe_print as _sp  # type: ignore

        _sp(msg)
    except Exception:
        print(msg)


def send_discord(webhook_url: str, channel: str, executor: str,
                 results: list, html_path: str) -> bool:
    """Kirim laporan ke Discord webhook.

    Return True bila ringkasan + file berhasil terkirim; False bila
    dilewati/gagal. Dipakai pemanggil untuk memutuskan hapus HTML lokal.
    """
    if not webhook_url:
        _log("[yellow][⚠️] Webhook URL tidak ditemukan. Skip Discord.[/yellow]")
        return False

    valid_results = [r for r in results if r.get("is_valid")]
    no_trans_count = sum(
        1 for r in results if r["status"] in ("no_transcript", "disabled", "unavailable")
    )
    all_hits = sum(len(r.get("hits", [])) for r in results)
    ch_label = channel_label(channel)

    kasta_global, warna = _kasta_global(results, valid_results)

    sorted_r = sorted(
        [r for r in results if r.get("persentase", 0) > 0],
        key=lambda x: x["persentase"], reverse=True,
    )
    scoreboard = ""
    hidden = 0
    for i, r in enumerate(sorted_r):
        if i < 3:
            scoreboard += (
                f"{i+1}. `{r['video_id']}` ➡️ **{r['persentase']}%** "
                f"{r['kasta_label'][:40]}\n"
            )
        else:
            hidden += 1
    if not scoreboard:
        scoreboard = "Tidak ada indikasi cegukan yang terdeteksi."
    if hidden > 0:
        scoreboard += f"\n**+{hidden} video lainnya** — lihat HTML untuk detail lengkap!"

    all_tier_counts = {"CORE": 0, "TYPO": 0, "SILENT": 0, "CONTEXT": 0, "FP": 0}
    keyword_freq: dict = {}
    for r in results:
        for tier, cnt in r.get("tier_counts", {}).items():
            if tier in all_tier_counts:
                all_tier_counts[tier] += cnt
        for hit in r.get("hits", []):
            txt = hit.get("text", "").strip()[:35]
            if txt:
                keyword_freq[txt] = keyword_freq.get(txt, 0) + 1

    tier_text = (
        f"CORE: **{all_tier_counts['CORE']}** | "
        f"TYPO: **{all_tier_counts['TYPO']}** | "
        f"SILENT: **{all_tier_counts['SILENT']}** | "
        f"CTX: **{all_tier_counts['CONTEXT']}**"
    )
    top_kw = sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)[:5]
    kw_text = "\n".join(f"• `{k}` ×{v}" for k, v in top_kw) if top_kw else "—"

    desc_val = _trunc(f"Laporan forensik V20 untuk {ch_label} telah selesai.", _DISCORD_DESC_LIMIT)
    target_val = _trunc(ch_label, _DISCORD_FIELD_LIMIT)
    exec_val = _trunc(executor, _DISCORD_FIELD_LIMIT)
    stat_val = _trunc(
        f"Total: {len(results)} | Valid: {len(valid_results)} | "
        f"No-Trans: {no_trans_count} | Hits: {all_hits}",
        _DISCORD_FIELD_LIMIT,
    )
    kw_val = _trunc(kw_text, _DISCORD_FIELD_LIMIT)
    tier_val = _trunc(tier_text, _DISCORD_FIELD_LIMIT)
    score_val = _trunc(scoreboard, _DISCORD_FIELD_LIMIT)

    payload = {
        "embeds": [{
            "title": kasta_global[:256],
            "color": warna,
            "description": desc_val,
            "fields": [
                {"name": "👤 Target", "value": target_val, "inline": True},
                {"name": "👷 Eksekutor", "value": exec_val, "inline": True},
                {"name": "📊 Statistik", "value": stat_val, "inline": False},
                {"name": "🔑 Keyword Terdeteksi (Top 5)", "value": kw_val, "inline": False},
                {"name": "📊 Tier Breakdown", "value": tier_val, "inline": False},
                {"name": "📈 Top Scoreboard", "value": score_val, "inline": False},
            ],
        }]
    }

    try:
        import requests as req_lib
    except ImportError:
        _log("[yellow][📦] Install requests...[/yellow]")
        import subprocess

        subprocess.run(
            ["pip", "install", "requests", "--break-system-packages", "-q"],
            check=True,
        )
        import requests as req_lib

    # ── LANGKAH 1: Kirim embed dulu (tanpa file) ──────────────────
    for attempt in range(2):
        try:
            resp = req_lib.post(webhook_url, json=payload, timeout=30)
            if resp.status_code in (200, 204):
                _log("[green][✅] Ringkasan terkirim ke Discord![/green]")
                break
            if resp.status_code == 429:
                retry_after = 2.0
                try:
                    retry_after = float(resp.json().get("retry_after", 2.0))
                except Exception:
                    pass
                retry_after = min(retry_after, 15.0) + 0.5
                if attempt == 0:
                    _log(f"[yellow][⚠️] Discord 429 rate-limited, retry dalam {retry_after:.1f}s...[/yellow]")
                    _time.sleep(retry_after)
                    continue
                _log("[red][❌] Discord tetap 429 setelah retry. Skip.[/red]")
                _log(f"[yellow]     File HTML disimpan lokal: {html_path}[/yellow]")
                return False
            if resp.status_code == 403:
                _log("[red][❌] Discord 403 Forbidden[/red]")
                _log("[yellow]     Cek apakah webhook masih aktif di Discord:[/yellow]")
                _log("[yellow]     Server → Edit Channel → Integrations → Webhooks[/yellow]")
                _log(f"[yellow]     File HTML disimpan lokal: {html_path}[/yellow]")
                return False
            _log(f"[yellow][⚠️] Discord response: {resp.status_code} — {resp.text[:100]}[/yellow]")
            break
        except Exception as e:
            _log(f"[red][❌] Gagal kirim embed: {e}[/red]")
            _log(f"[yellow]     File HTML disimpan lokal: {html_path}[/yellow]")
            return False

    # ── LANGKAH 2: Attach file HTML hanya jika ukuran aman ────────
    if not _os.path.exists(html_path):
        return False

    file_size_mb = _os.path.getsize(html_path) / (1024 * 1024)
    if file_size_mb > _DISCORD_FILE_MAX_MB:
        _log(f"[yellow][⚠️] HTML terlalu besar ({file_size_mb:.1f}MB), tidak bisa attach ke Discord.[/yellow]")
        _log(f"[yellow]     File disimpan lokal: {html_path}[/yellow]")
        return False

    _log(f"[dim][📎] Mengirim file HTML ({file_size_mb:.2f}MB)...[/dim]")
    try:
        fname = _os.path.basename(html_path)
        with open(html_path, "rb") as f:
            resp2 = req_lib.post(
                webhook_url,
                data={"payload_json": _json.dumps({"content": f"📄 Laporan lengkap {ch_label}:"})},
                files={"file": (fname, f, "text/html")},
                timeout=60,
            )
        if resp2.status_code in (200, 204):
            _log("[green][✅] File HTML berhasil dikirim ke Discord![/green]")
            return True
        _log(f"[yellow][⚠️] File response: {resp2.status_code} — file disimpan lokal[/yellow]")
        _log(f"[yellow]     {html_path}[/yellow]")
        return False
    except Exception as e:
        _log(f"[red][❌] Gagal kirim file: {e}[/red]")
        _log(f"[yellow]     File disimpan lokal: {html_path}[/yellow]")
        return False
