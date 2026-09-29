"""Preferensi persisten + lokasi config (`cs_core.settings`).

Semua path dihitung dari **lokasi paket**, bukan CWD — supaya `cs21` bisa
dijalankan dari folder mana pun (mis. `cd /sdcard && cs21`).

Lokasi config: `CS_CONFIG_DIR` > `<repo>/.cs20`.
Preferensi: `<config_dir>/settings.json` (JSON kecil, toleran file rusak).
Channel tersimpan: `<config_dir>/channels.txt` (kompatibel dengan engine lama).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

__all__ = [
    "repo_root",
    "config_dir",
    "settings_path",
    "channels_path",
    "history_path",
    "Settings",
    "load",
    "save",
    "update",
    "FuzzyMode",
]

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent

FuzzyMode = str  # "auto" | "on" | "off"

@dataclass
class Settings:
    """Preferensi user yang bertahan antar sesi."""

    lang: str = "id"
    fuzzy: FuzzyMode = "auto"
    jobs: int = 4
    limit: int = 20
    notify: bool = True
    wake_lock: bool = True
    ui: str = "auto"          # auto | ptk | plain
    last_channel: str = ""
    last_mode: str = ""
    verbose: bool = False

    def with_(self, **kw) -> "Settings":
        return replace(self, **kw)

def repo_root() -> Path:
    """Folder repo (tempat `cs20_engine.py` dkk berada)."""
    return _REPO_ROOT

def config_dir(override: str | os.PathLike | None = None) -> Path:
    """Direktori config; dibuat bila belum ada."""
    if override:
        path = Path(override).expanduser()
    elif os.environ.get("CS_CONFIG_DIR"):
        path = Path(os.environ["CS_CONFIG_DIR"]).expanduser()
    else:
        path = _REPO_ROOT / ".cs20"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path

def settings_path(override=None) -> Path:
    return config_dir(override) / "settings.json"

def channels_path(override=None) -> Path:
    return config_dir(override) / "channels.txt"

def history_path(override=None) -> Path:
    return config_dir(override) / "history"

# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------
def _coerce(raw: dict) -> Settings:
    """Bangun Settings dari dict mentah; buang nilai yang tidak masuk akal."""
    base = Settings()
    if not isinstance(raw, dict):
        return base

    out = base
    lang = str(raw.get("lang", base.lang) or base.lang).strip().lower()
    out = out.with_(lang=lang or base.lang)

    fuzzy = str(raw.get("fuzzy", base.fuzzy) or base.fuzzy).strip().lower()
    out = out.with_(fuzzy=fuzzy if fuzzy in ("auto", "on", "off") else base.fuzzy)

    for key, low, high in (("jobs", 1, 16), ("limit", 0, 100000)):
        try:
            val = int(raw.get(key, getattr(base, key)))
        except (TypeError, ValueError):
            val = getattr(base, key)
        out = out.with_(**{key: min(max(val, low), high)})

    for key in ("notify", "wake_lock", "verbose"):
        val = raw.get(key, getattr(base, key))
        out = out.with_(**{key: bool(val)})

    ui = str(raw.get("ui", base.ui) or base.ui).strip().lower()
    out = out.with_(ui=ui if ui in ("auto", "ptk", "plain") else base.ui)

    for key in ("last_channel", "last_mode"):
        val = raw.get(key, getattr(base, key))
        out = out.with_(**{key: str(val or "").strip()})

    return out

def load(override=None) -> Settings:
    """Baca settings; file hilang/rusak -> default (tidak pernah fatal)."""
    path = settings_path(override)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    return _coerce(raw)

def save(settings: Settings, override=None) -> bool:
    """Tulis settings atomic. Return True bila berhasil."""
    path = settings_path(override)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return True
    except OSError:
        return False

def update(override=None, **kw) -> Settings:
    """Ubah beberapa field lalu simpan."""
    settings = load(override).with_(**kw)
    save(settings, override)
    return settings
