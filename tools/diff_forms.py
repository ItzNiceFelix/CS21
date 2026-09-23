#!/usr/bin/env python3
"""Fase 2 — banding forms baru vs regex baseline `spec_data.py`.

Aturan: untuk setiap bahasa & tier, pattern CORE lama HARUS masih tercakup
oleh pattern baru. TYPO/CONTEXT boleh berubah/di-generate (P10); CORE wajib
aman (subset-superset).

Metode:
1. Setiap pattern CORE baseline dibersihkan jadi *probe* konkret (kelas `[..]`
   -> karakter pertama, kuantifier `+`/`*`/`?` dibuang, boundary/alternasi
   diekstrak). Ini string yang PASTI di-match pattern lama.
2. Probe dicek terhadap `combined_prefilter` spec baru. Bila pattern baru
   (hasil generate) tetap mencocokkan probe lama -> form CORE tidak hilang.

Exit 1 bila ada probe CORE lama yang tak lagi match. `spec_data.py` tetap
dibaca sebagai baseline referensi (jangan dihapus).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core.languages import load  # noqa: E402
from cs_core.languages import spec_data  # noqa: E402

_META_RE = re.compile(r"(?<!\\)[+*?]")


def _probes(pat: str) -> list[str]:
    """Turunkan probe literal dari satu pattern regex lama."""
    p = pat
    p = p.replace(r"\b", "").replace(r"\s*", "").replace(r"\s+", " ")
    p = p.replace(r"\\b", "")
    # alternasi top-level: pecah
    if "|" in p and "(" not in p:
        return [q for part in p.split("|") if (q := _probe_one(part))]
    return [q for q in [_probe_one(p)] if q]


def _probe_one(p: str) -> str:
    # kelas char: [abc] -> a ; [uo] -> u
    def _cls(m):
        body = m.group(1).replace("^", "")
        return body[0] if body else ""

    p = re.sub(r"\[([^\]]*)\]", _cls, p)
    p = _META_RE.sub("", p)          # buang + * ?
    p = re.sub(r"\{[^}]*\}", "", p)  # buang {n,m}
    p = p.replace(r"\s", " ")
    p = p.replace("(", "").replace(")", "")
    p = p.replace(r"\\*", "*")
    p = p.replace("\\", "")
    return p.strip()


def _check_lang(lang: str) -> tuple[bool, list[str]]:
    """Cek probe CORE lama HANYA terhadap regex CORE tier (bukan semua tier).

    Versi lama memakai `combined_prefilter` (gabungan SEMUA tier + romanized),
    sehingga form CORE yang hilang bisa lolos karena tertutup pattern tier lain
    (false-negative). Di sini probe diuji ke CORE spec saja.
    """
    spec = load(lang).compile()
    missing: list[str] = []
    core = spec.core_for("CORE")
    core_regexes = list(core.regexes) if core else []

    for pat in spec_data.KEYWORD_TIERS.get(lang, {}).get("CORE", {}).get("patterns", []):
        for probe in _probes(pat):
            if not probe:
                continue
            if any(r.search(probe) for r in core_regexes):
                continue
            missing.append(f"{probe!r} (from {pat!r})")
    return (not missing), missing


def compare() -> int:
    failures = 0
    for lang in spec_data.KEYWORD_TIERS:
        ok, missing = _check_lang(lang)
        if ok:
            print(f"[OK]   {lang}/CORE: semua probe CORE lama tercakup")
        else:
            failures += 1
            print(f"[LOSS] {lang}/CORE: {len(missing)} probe hilang:")
            for m in missing:
                print(f"        {m}")
    if failures:
        print(f"\nGAGAL: {failures} bahasa kehilangan form CORE")
        return 1
    print("\nAMAN: 0 form CORE hilang")
    return 0


def main(argv=None) -> int:
    return compare()


if __name__ == "__main__":
    raise SystemExit(main())
