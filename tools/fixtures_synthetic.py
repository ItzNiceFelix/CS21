#!/usr/bin/env python3
"""Fase 0 — generator segmen sintetis (tanpa network).

Menghasilkan JSON berisi kumpulan kasus uji untuk baseline Fase 0:
  (a) zero_core      — 0 hit CORE
  (b) maraton        — single-cluster panjang
  (c) multisisi      — 2 cluster CORE
  (d) silent         — silent treatment
  (e) dedup_float    — dua segmen beda durasi di detik sama
  (f) typo_asr       — jegukan / segukan / cekukan

Default menulis ke tools/synthetic_segments.json (BUKAN tests/fixtures/).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent / "synthetic_segments.json"


def _seg(sec: int, text: str, duration: float | None = None) -> dict:
    base = {"sec": sec, "text": text}
    if duration is not None:
        base["duration"] = duration
    return base


def build_cases() -> dict:
    """Return {"cases": {name: {"segments": [...], "note": str}}}."""
    cases: dict = {}

    # (a) 0 hit CORE — keyword hanya tier FP/CONTEXT, tak ada CORE sama sekali.
    cases["zero_core"] = {
        "note": "hanya FP/CONTEXT, 0 CORE -> kasta AMBIGU",
        "segments": [
            _seg(0, "eh ada nyendawa tadi"),
            _seg(30, "kayaknya cuma tersedak kopi"),
            _seg(60, "hiks hiks sedih banget"),
        ],
    }

    # (b) maraton — satu cluster panjang, banyak hit CORE berturut sepanjang >30 menit.
    marathon = []
    for i in range(40):
        marathon.append(_seg(i * 60, f"cegukan lagi nih menit {i}"))
    cases["maraton_single_cluster"] = {
        "note": "40 hit CORE tersebar 39 menit, gap < 20 menit -> 1 cluster",
        "segments": marathon,
    }

    # (c) multisisi — 2 cluster CORE dipisah > 20 menit (> gap default).
    cases["multisisi"] = {
        "note": "dua gugus CORE dipisah 40 menit -> >=2 cluster",
        "segments": [
            _seg(0, "cegukan mulai"),
            _seg(10, "cegukan lagi"),
            _seg(20, "cegukan terus"),
            _seg(30, "cegukan juga"),
            _seg(3000, "cegukan balik lagi"),  # 50 menit, > gap 20 menit
            _seg(3010, "cegukan kambuh"),
            _seg(3020, "cegukan kambuh lagi"),
            _seg(3030, "cegukan kambuh terus"),
        ],
    }

    # (d) silent treatment — pola SILENT (cegukan gak ilang / capek cegukan).
    cases["silent_treatment"] = {
        "note": "pola SILENT dengan CORE -> kasta SILENT",
        "segments": [
            _seg(0, "cegukan gak ilang dari tadi"),
            _seg(60, "capek cegukan"),
            _seg(120, "cegukan terus mulu"),
        ],
    }

    # (e) dedup float — dua segmen di detik start yang sama, durasi berbeda.
    cases["dedup_float"] = {
        "note": "dua segmen start=120 durasi beda -> uji dedup_key float (P8)",
        "segments": [
            _seg(0, "cegukan awal"),
            _seg(120, "cegukan", duration=1.2),
            _seg(120, "cegukan panjang", duration=2.8),
            _seg(180, "cegukan penutup"),
        ],
    }

    # (f) typo ASR — variasi typo misshear.
    cases["typo_asr"] = {
        "note": "jegukan/segukan/cekukan -> tier TYPO/CORE",
        "segments": [
            _seg(0, "aku jegukan terus"),
            _seg(30, "segukan nih kayaknya"),
            _seg(60, "cekukan mulu"),
        ],
    }

    return {"cases": cases}


def build_document() -> dict:
    cases = build_cases()["cases"]
    flat = []
    for name, data in cases.items():
        flat.extend(data["segments"])
    return {
        "meta": {
            "tool": "fixtures_synthetic.py",
            "dedup_mode": "baseline",
            "cluster_mode": "baseline",
            "case_names": list(cases),
        },
        # `segments` = gabungan semua kasus, untuk pure_scoring_probe default.
        "segments": flat,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fixtures_synthetic.py",
        description="Generate segmen sintetis Fase 0 (tanpa network).",
    )
    p.add_argument(
        "--out",
        help=f"path output (default: {DEFAULT_OUT}); pakai '-' untuk stdout",
    )
    args = p.parse_args(argv)

    doc = build_document()
    text = json.dumps(doc, ensure_ascii=False, indent=2)

    if args.out == "-":
        print(text)
        return 0

    out = Path(args.out) if args.out else DEFAULT_OUT
    out.write_text(text, encoding="utf-8")
    print(f"[OK] tulis {len(doc['segments'])} segmen / {len(doc['cases'])} kasus -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
