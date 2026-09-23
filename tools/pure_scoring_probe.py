#!/usr/bin/env python3
"""Fase 0 — probe scoring murni (tanpa fetch transcript).

Memanggil blok cluster+score+kasta setiap engine langsung, supaya rumus terekam
terpisah dari efek fetch transkrip. Boleh mengimpor fungsi privat engine.

Semua engine di-import lazy; modul ini sendiri aman di-import tanpa deps berat.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Engine lama mencetak emoji ke stdout; di console non-UTF8 (Windows dev) itu
# meledak. Paksa UTF-8 bila bisa, supaya import engine tetap jalan.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from tools import baseline_capture as bc  # noqa: E402


def probe(segments: list, lang: str) -> dict:
    """Jalankan blok scoring murni tiap engine atas `segments`.

    `segments`: list dict. Gaya index {sec,text} atau yt-api {start,duration,text}.
    Return {"lang":..., "input":..., "e":..., "ie":..., "ae":...}.
    """
    index_segments = bc._to_index_segments(segments)
    out: dict = {
        "lang": lang,
        "input": {
            "count": len(segments),
            "index_segments": index_segments,
        },
        "e": None,
        "ie": None,
        "ae": None,
    }

    # E tak punya entry-point scoring murni; pakai segmen sebagai raw dan
    # reimplementasi scoring via helper internal. Karena analyze_video wajib
    # fetch, di sini kita RECORD penanda bahwa E tak tersedia murni.
    out["e"] = {"skipped": "analyze_video butuh fetch; pakai IE/AE utk scoring murni"}

    try:
        import cs20_engine
        from cs20_index_engine import _analyze_from_segments

        cs20_engine._init_lang(lang)
        out["ie"] = bc._json_safe(
            _analyze_from_segments(
                "PROBE",
                "PROBE",
                index_segments,
                cs20_engine.COMPILED_TIERS,
                cs20_engine.ALL_PATTERNS_COMBINED,
            )
        )
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — engine bisa sys.exit saat rich absen
        out["ie"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        from cs20_age_engine import _analyze_segments, _load_fuzzy_engine

        compiled, combined, ok = _load_fuzzy_engine(lang)
        out["ae"] = bc._json_safe(
            _analyze_segments("PROBE", "PROBE", index_segments, compiled, combined)
        )
        out["ae"]["fuzzy_available"] = ok
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        out["ae"] = {"error": f"{type(exc).__name__}: {exc}"}

    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="pure_scoring_probe.py",
        description="Fase 0: scoring murni (cluster+score+kasta) tiap engine, tanpa fetch.",
    )
    p.add_argument("--lang", default="id")
    p.add_argument("--segments", help="path JSON list segmen; default baca synthetic_segments.json")
    p.add_argument("--out", help="path output JSON (default stdout)")
    args = p.parse_args(argv)

    seg_path = Path(args.segments) if args.segments else Path(__file__).parent / "synthetic_segments.json"
    if not seg_path.exists():
        print(f"[!] File segmen tak ada: {seg_path}", file=sys.stderr)
        return 2

    data = json.loads(seg_path.read_text(encoding="utf-8"))
    segments = data.get("segments", data) if isinstance(data, dict) else data
    result = probe(segments, args.lang)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
