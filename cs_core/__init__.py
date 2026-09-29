"""cs_core — inti Cegukan Seeker V21 (pure stdlib, tanpa `rich`).

Isi paket:

- CLI + menu interaktif: `cli.py`, `menu.py`, `tui.py`, `doctor.py`, `settings.py`
- Kontrak error/exit code: `errors.py`
- Integrasi Android/Termux (opsional): `termux.py`
- Inti pencocokan: `text.py`, `tokens.py`, `languages/`, `matching.py`,
  `scoring.py`, `transcript.py`, `cache.py`, `report.py`, `compat.py`
- Jembatan engine lama: `engine_compat.py`

Entry point: `python -m cs_core` (tanpa argumen = menu interaktif).
"""

__version__ = "21.0.0"
