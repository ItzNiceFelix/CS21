"""HTML rows minimal untuk Fase 1.

P5: highlight dibangun dari match offset sekali jalan (bukan `pat.sub`
bertingkat), jadi TIDAK ada `<span>` di dalam `<span>`. `build_html` penuh
menyusul Fase 6.
"""

from __future__ import annotations

import html as _html

from . import config as _config

__all__ = ["build_html_rows", "escape_html", "highlight_matches"]

_TIER_CLASS = {"CORE": "core", "TYPO": "typo", "SILENT": "silent", "CONTEXT": "ctx"}


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
