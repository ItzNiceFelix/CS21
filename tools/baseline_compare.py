#!/usr/bin/env python3
"""Fase 0 — pembanding dua file baseline.

`compare(file_a, file_b)` membandingkan per-field per-video lalu mengembalikan
exit code: 0 = identik, 1 = ada beda. `--ignore-fields` untuk field yang memang
beda antar-varian (mis. `html_rows` saat mode IMPROVED).

Hanya pakai stdlib — aman dijalankan tanpa dependency engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Field di level video yang selalu berbeda antar-variasi dan biasanya diabaikan.
DEFAULT_IGNORE_FIELDS = ("html_rows",)


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fmt(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 160 else text[:157] + "..."


def _diff_value(a, b, path: str, out: list[str], ignore: set[str]) -> None:
    """Diff rekursif; tulis baris readable ke `out`. Key di `ignore` dilewati."""
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        out.append(f"    {path}: tipe beda {type(a).__name__} != {type(b).__name__}")
        out.append(f"      A = {_fmt(a)}")
        out.append(f"      B = {_fmt(b)}")
        return
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key in ignore:
                continue
            if key not in a:
                out.append(f"    {path}.{key}: hanya di B = {_fmt(b[key])}")
            elif key not in b:
                out.append(f"    {path}.{key}: hanya di A = {_fmt(a[key])}")
            else:
                _diff_value(a[key], b[key], f"{path}.{key}", out, ignore)
        return
    if isinstance(a, list):
        if len(a) != len(b):
            out.append(f"    {path}: panjang beda {len(a)} != {len(b)}")
        for i in range(min(len(a), len(b))):
            _diff_value(a[i], b[i], f"{path}[{i}]", out, ignore)
        return
    if a != b:
        out.append(f"    {path}: A = {_fmt(a)}  |  B = {_fmt(b)}")


def compare(
    file_a: str,
    file_b: str,
    ignore_fields: tuple[str, ...] = (),
) -> int:
    """Bandingkan dua baseline. Return 0 bila identik, 1 bila ada beda."""
    doc_a, doc_b = _load(file_a), _load(file_b)
    ignore = set(ignore_fields)

    diffs: list[str] = []

    # Meta
    for key in sorted(set(doc_a.get("meta", {})) | set(doc_b.get("meta", {}))):
        if key in ignore:
            continue
        va = doc_a.get("meta", {}).get(key)
        vb = doc_b.get("meta", {}).get(key)
        if va != vb:
            diffs.append(f"  meta.{key}: A = {_fmt(va)}  |  B = {_fmt(vb)}")

    vids_a = {v.get("video_id"): v for v in doc_a.get("videos", [])}
    vids_b = {v.get("video_id"): v for v in doc_b.get("videos", [])}

    for vid in sorted(set(vids_a) | set(vids_b)):
        if vid not in vids_a:
            diffs.append(f"  [{vid}] hanya ada di B")
            continue
        if vid not in vids_b:
            diffs.append(f"  [{vid}] hanya ada di A")
            continue

        va, vb = vids_a[vid], vids_b[vid]
        local: list[str] = []
        for key in sorted(set(va) | set(vb)):
            if key in ignore:
                continue
            if key not in va:
                local.append(f"    {key}: hanya di B")
            elif key not in vb:
                local.append(f"    {key}: hanya di A")
            else:
                _diff_value(va[key], vb[key], key, local, ignore)
        if local:
            diffs.append(f"  [{vid}]")
            diffs.extend(local)

    if not diffs:
        print(f"IDENTIK: {file_a} == {file_b}")
        return 0

    print(f"BEDA: {file_a} != {file_b}")
    for line in diffs:
        print(line)
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="baseline_compare.py",
        description="Bandingkan dua file baseline; exit 0 = identik, 1 = beda.",
    )
    p.add_argument("file_a", nargs="?", help="baseline pertama")
    p.add_argument("file_b", nargs="?", help="baseline kedua")
    p.add_argument(
        "--ignore-fields",
        default="",
        help=f"field diabaikan, dipisah koma (default pakai bila kosong: {','.join(DEFAULT_IGNORE_FIELDS)})",
    )
    args = p.parse_args(argv)

    if not args.file_a or not args.file_b:
        # DoD termudah: tanpa argumen ke dua file, self-compare file_a.
        if args.file_a and not args.file_b:
            args.file_b = args.file_a
        else:
            p.print_help()
            return 2

    if args.ignore_fields:
        ignore = tuple(f.strip() for f in args.ignore_fields.split(",") if f.strip())
    else:
        ignore = DEFAULT_IGNORE_FIELDS

    return compare(args.file_a, args.file_b, ignore)


if __name__ == "__main__":
    raise SystemExit(main())
