"""Pencarian di dua sumber: JSON index (Index Mode) dan cache transkrip.

Kenapa modul sendiri:

- `cs20_index_parser.search_index_batch` memakai `glob(index_dir/*.json)` yang
  **tidak rekursif**, sedangkan Index Mode menulis ke
  `{root}/{channel}/batch_NN/index/*.json`. Akibatnya pencarian setelah sesi
  index selesai selalu kosong tanpa pesan error.
- Modul itu juga mengimpor `rich` di top-level, jadi `cs21 search` mati total
  bila `rich` tidak terpasang — padahal pencariannya murni `re`.
- Cache transkrip (`{root}/transcripts/*.jsonl.gz`) tidak pernah dicari,
  padahal isinya segmen yang sama.

Semantik query sengaja **sama** dengan parser lama: `OR` antar-clausa,
`AND` di dalam clausa, `"frasa"` dihormati, tiap term minimal 2 karakter.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import cache as _cache
from .video import video_url

__all__ = [
    "SearchHit",
    "SearchResult",
    "parse_query",
    "index_dirs",
    "search",
    "search_index",
    "search_cache",
]

_PHRASE_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_OPERATOR_RE = re.compile(r"\b(?:AND|OR)\b", re.IGNORECASE)
_OR_SPLIT_RE = re.compile(r"\bOR\b", re.IGNORECASE)

@dataclass(frozen=True)
class SearchHit:
    """Satu baris transkrip yang cocok."""

    sec: float
    time: str
    text: str
    url: str
    terms: tuple = ()

@dataclass
class SearchResult:
    """Hasil per video."""

    video_id: str
    source: str                  # "index" | "cache"
    lang: str = ""
    channel: str = ""
    path: str = ""
    hits: list = field(default_factory=list)

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    @property
    def first_sec(self) -> float:
        return self.hits[0].sec if self.hits else 0.0

def sec_to_hms(sec: float) -> str:
    total = int(sec or 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------
def parse_query(query: str) -> list[list[re.Pattern]]:
    """`"a b" OR c AND d` -> `[[re_a, re_b], [re_c, re_d]]` (OR antar-grup)."""
    groups: list[list[re.Pattern]] = []
    for clause in _OR_SPLIT_RE.split(query or ""):
        terms: list[re.Pattern] = []
        for phrase_match in _PHRASE_RE.finditer(clause):
            phrase = (phrase_match.group(1) or phrase_match.group(2) or "").strip()
            if phrase:
                terms.append(re.compile(re.escape(phrase), re.IGNORECASE))
        remainder = _OPERATOR_RE.sub(" ", _PHRASE_RE.sub("", clause))
        for word in remainder.split():
            word = word.strip().strip("\"'")
            if len(word) >= 2:
                terms.append(re.compile(re.escape(word), re.IGNORECASE))
        if terms:
            groups.append(terms)
    return groups

def _match_groups(segments: list[dict], groups: list[list[re.Pattern]]) -> list[SearchHit]:
    """Baris yang cocok, dengan AND di level video (seperti parser lama)."""
    if not groups:
        return []
    full_text = " ".join(str(s.get("text", "")) for s in segments)
    active = [t for g in groups if all(t.search(full_text) for t in g) for t in g]
    if not active:
        return []

    hits: list[SearchHit] = []
    seen: set[float] = set()
    for seg in segments:
        sec = float(seg.get("sec", seg.get("start", 0)) or 0)
        text = str(seg.get("text", ""))
        if sec in seen or not any(t.search(text) for t in active):
            continue
        seen.add(sec)
        hits.append(SearchHit(sec=sec, time=sec_to_hms(sec), text=text,
                              url="", terms=tuple(t.pattern for t in active)))
    hits.sort(key=lambda h: h.sec)
    return hits

# ---------------------------------------------------------------------------
# sumber: JSON index
# ---------------------------------------------------------------------------
def index_dirs(root: str | os.PathLike) -> list[Path]:
    """Semua folder yang benar-benar berisi `*.json` index.

    Menelusuri sampai kedalaman 4 supaya struktur
    `{root}/{channel}/batch_NN/index/` ikut ketemu, tanpa memindai seluruh
    filesystem.
    """
    base = Path(root)
    if not base.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        depth = len(Path(dirpath).relative_to(base).parts)
        if depth >= 4:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if any(name.endswith(".json") and name not in ("meta.json", "status.json")
               for name in filenames):
            found.append(Path(dirpath))
    return found

def _iter_index_files(root: str | os.PathLike):
    seen: set[Path] = set()
    for folder in index_dirs(root):
        for path in sorted(folder.glob("*.json")):
            if path.name in ("meta.json", "status.json") or path in seen:
                continue
            seen.add(path)
            yield path

def search_index(root: str | os.PathLike, query: str, channel: str = "") -> list[SearchResult]:
    """Cari di semua JSON index di bawah `root` (rekursif).

    `channel` menyaring hasil ke satu channel; folder di luar struktur
    `{channel}/batch_NN/index` (channel tak diketahui) tidak ikut bila filter
    aktif.
    """
    groups = parse_query(query)
    if not groups:
        return []
    wanted = (channel or "").strip().lstrip("@").lower()
    results: list[SearchResult] = []
    for path in _iter_index_files(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("status") != "ok":
            continue
        segments = data.get("segments") or []
        video_id = str(data.get("video_id") or path.stem)
        if not segments:
            continue
        hits = _match_groups(segments, groups)
        if not hits:
            continue
        found_channel = _channel_of(path)
        if wanted and found_channel.lower() != wanted:
            continue
        hits = [SearchHit(sec=h.sec, time=h.time, text=h.text,
                          url=video_url(video_id, h.sec), terms=h.terms) for h in hits]
        results.append(SearchResult(
            video_id=video_id,
            source="index",
            lang=str(data.get("lang") or ""),
            channel=found_channel,
            path=str(path),
            hits=hits,
        ))
    return results

def _channel_of(path: Path) -> str:
    """Nama channel dari lokasi file index.

    Dua tata letak didukung:
    - `{root}/{channel}/batch_NN/index/{video}.json` -> `channel`
    - `{root}/{channel}/{video}.json`               -> `channel`

    Versi lama selalu mengambil `parent.parent.parent`, yang pada tata letak
    kedua menghasilkan nama folder sementara (mis. `tmp`), bukan channel.
    """
    parts = path.parent.parts
    if len(parts) >= 3 and parts[-1] == "index" and parts[-2].startswith("batch_"):
        return parts[-3]
    # Datar: file index langsung di dalam folder channel, jadi `path.parent`
    # ITU folder channel (`parts[-1]`, bukan `parts[-2]` = parent dari root).
    if len(parts) >= 1:
        return parts[-1]
    return ""

# ---------------------------------------------------------------------------
# sumber: cache transkrip
# ---------------------------------------------------------------------------
def _read_cache_segments(path: Path) -> tuple[list[dict], dict]:
    segments: list[dict] = []
    meta: dict = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if "_meta" in obj:
                    meta = obj["_meta"] or {}
                    continue
                seg = obj.get("seg")
                if isinstance(seg, dict) and "sec" in seg and "text" in seg:
                    segments.append({"sec": seg["sec"], "text": seg["text"]})
    except (OSError, EOFError):
        return [], {}
    return segments, meta

def search_cache(root=None, query: str = "", channel: str = "") -> list[SearchResult]:
    """Cari di cache transkrip di SEMUA root (`{root}/transcripts/*.jsonl.gz`).

    Root dibaca lengkap seperti `cache.read`, bukan cuma primer: cache lama di
    home PRoot/Termux tetap ketemu setelah lokasi primer berpindah.

    Filter `channel` butuh header `_meta.channel`. Cache lama (sebelum field
    itu ditulis) tidak punya informasi channel sehingga **dibuang** saat
    filter aktif — lebih baik kosong daripada hasil yang salah channel.
    """
    groups = parse_query(query)
    if not groups:
        return []
    results: list[SearchResult] = []
    seen: set[str] = set()
    for folder in _cache.all_cache_dirs(root):
        for path in sorted(folder.glob("*.jsonl.gz")):
            stem = path.name[: -len(".jsonl.gz")]
            video_id, _, lang = stem.partition(".")
            if video_id in seen:
                continue  # video sama di root lain: primer menang
            segments, meta = _read_cache_segments(path)
            if not segments:
                continue
            if channel and meta.get("channel") != channel:
                continue
            hits = _match_groups(segments, groups)
            if not hits:
                continue
            seen.add(video_id)
            hits = [SearchHit(sec=h.sec, time=h.time, text=h.text,
                              url=video_url(video_id, h.sec), terms=h.terms) for h in hits]
            results.append(SearchResult(
                video_id=video_id,
                source="cache",
                lang=lang,
                channel=str(meta.get("channel") or channel or ""),
                path=str(path),
                hits=hits,
            ))
    return results

# ---------------------------------------------------------------------------
# gabungan
# ---------------------------------------------------------------------------
def search(query: str, *, index_root=None, cache_root=None,
           channel: str = "", sources: tuple = ("index", "cache")) -> list[SearchResult]:
    """Cari di index dan/atau cache; satu hasil per video (index menang)."""
    merged: dict[str, SearchResult] = {}
    if "index" in sources and index_root:
        for res in search_index(index_root, query, channel):
            merged[res.video_id] = res
    if "cache" in sources:
        for res in search_cache(cache_root, query, channel):
            merged.setdefault(res.video_id, res)

    out = list(merged.values())
    out.sort(key=lambda r: (-r.hit_count, r.video_id))
    return out
