"""Lapisan UI interaktif (prompt_toolkit opsional, fallback readline/plain).

Tiga backend, dipilih otomatis:

- ``ptk``   — `prompt_toolkit` terpasang & stdout TTY: pemilih panah + filter.
- ``plain`` — TTY tanpa prompt_toolkit: input angka + tab-completion (readline).
- ``pipe``  — bukan TTY (cron/pipe): tanpa prompt, langsung baca stdin.

Prinsip: TIDAK PERNAH melempar exception ke pemanggil. Kalau prompt_toolkit
error di tengah jalan, otomatis turun ke ``plain``.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

__all__ = ["Option", "UI", "ExitMenu"]

# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------
_RESET = "\033[0m"
_CODES = {
    "dim": "\033[2m", "bold": "\033[1m",
    "red": "\033[0;31m", "green": "\033[0;32m", "yellow": "\033[0;33m",
    "blue": "\033[0;34m", "magenta": "\033[0;35m", "cyan": "\033[0;36m",
    "white": "\033[1;37m",
}

class ExitMenu(Exception):
    """Ctrl+C / EOF / 'q' di level pemilih -> keluar menu dengan rapi."""

# Jumlah opsi yang dicetak sekaligus di mode plain (di atas ini: filter dulu).
_PLAIN_PAGE = 16

@dataclass(frozen=True)
class Option:
    """Satu pilihan di pemilih."""

    key: str
    label: str
    detail: str = ""
    badge: str = ""

    def text(self) -> str:
        parts = [self.label]
        if self.detail:
            parts.append(f"  {self.detail}")
        if self.badge:
            parts.append(f"  [{self.badge}]")
        return "".join(parts)

# ---------------------------------------------------------------------------
# deteksi kemampuan terminal
# ---------------------------------------------------------------------------
def _tty(stream=None) -> bool:
    stream = stream or sys.stdin
    try:
        return bool(stream.isatty())
    except Exception:
        return False

def _term_ok() -> bool:
    term = (os.environ.get("TERM") or "").strip().lower()
    return term not in ("", "dumb", "unknown")

def _unicode_ok() -> bool:
    if not _term_ok():
        return False
    enc = (getattr(sys.stdout, "encoding", "") or "utf-8").lower()
    try:
        "─│╭╮╰╯█▸".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return False
    return True

def have_prompt_toolkit() -> bool:
    """True bila `prompt_toolkit` bisa diimpor (cache sekali)."""
    global _HAVE_PTK
    if _HAVE_PTK is None:
        try:
            import prompt_toolkit  # noqa: F401
            _HAVE_PTK = True
        except Exception:
            _HAVE_PTK = False
    return _HAVE_PTK

_HAVE_PTK: bool | None = None

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class UI:
    """Pembungkus kecil untuk semua I/O interaktif."""

    def __init__(self, *, width: int | None = None, mode: str = "auto",
                 colors: bool | None = None, interactive: bool | None = None):
        self.interactive = _tty() if interactive is None else interactive
        self.colors = (
            (self.interactive and _term_ok() and not os.environ.get("NO_COLOR"))
            if colors is None else colors
        )
        self.unicode = _unicode_ok()
        self._width_override = width
        self.mode = self._resolve_mode(mode)
        self._completer_installed = False

    # -- dasar ------------------------------------------------------------
    def _resolve_mode(self, wanted: str) -> str:
        if not self.interactive:
            return "pipe"
        if wanted == "plain":
            return "plain"
        if wanted == "ptk" and have_prompt_toolkit():
            return "ptk"
        if wanted == "auto" and have_prompt_toolkit():
            return "ptk"
        return "plain"

    @property
    def width(self) -> int:
        if self._width_override:
            return max(24, self._width_override)
        try:
            cols = shutil.get_terminal_size((80, 24)).columns
        except Exception:
            cols = 80
        return max(24, min(cols, 100))

    def style(self, text: str, *names: str) -> str:
        if not self.colors or not names:
            return text
        prefix = "".join(_CODES.get(n, "") for n in names)
        return f"{prefix}{text}{_RESET}"

    def say(self, text: str = "") -> None:
        print(text)

    def rule(self, char: str | None = None) -> None:
        ch = char or ("─" if self.unicode else "-")
        print(self.style(ch * self.width, "dim"))

    def title(self, text: str) -> None:
        """Judul dalam kotak; total lebar tidak pernah melebihi `self.width`."""
        left, right = ("╭", "╮") if self.unicode else ("+", "+")
        edge = "─" if self.unicode else "-"
        # 2 border + 2 spasi + teks => sisa untuk isi kotak
        label = text
        inner = self.width - 5 - len(label)
        if inner < 0:
            label = text[: max(0, self.width - 5)]
            inner = max(0, self.width - 5 - len(label))
        print(self.style(f"{left}{edge} {label} " + edge * inner + right, "cyan"))

    def kv(self, key: str, value: str, key_width: int = 10) -> None:
        """Baris `key: value`; `key_width=0` -> tanpa padding (nilai saja)."""
        if key_width <= 0 or not key:
            print(f"  {value}")
            return
        print(f"  {self.style(key.ljust(key_width), 'dim')}{value}")

    def ok(self, text: str) -> None:
        print(f"  {self.style('✓', 'green')} {text}")

    def warn(self, text: str) -> None:
        print(f"  {self.style('!', 'yellow')} {text}")

    def err(self, text: str) -> None:
        print(f"  {self.style('✗', 'red')} {text}", file=sys.stderr)

    def info(self, text: str) -> None:
        print(f"  {self.style('·', 'dim')} {text}")

    def clear(self) -> None:
        if not self.interactive:
            return
        try:
            print("\033[2J\033[H", end="")
        except Exception:
            pass

    # -- input dasar -------------------------------------------------------
    def ask(self, prompt: str, *, default: str = "",
            validate: Callable[[str], str | None] | None = None) -> str:
        """Input teks. `validate` -> pesan error (None = valid)."""
        suffix = f" [{default}]" if default else ""
        while True:
            raw = self._read(f"  {prompt}{suffix}: ")
            if raw is None:
                raise ExitMenu()
            value = raw.strip() or default
            if validate:
                problem = validate(value)
                if problem:
                    self.warn(problem)
                    continue
            return value

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        hint = "Y/n" if default else "y/N"
        raw = self._read(f"  {prompt} ({hint}): ")
        if raw is None:
            raise ExitMenu()
        raw = raw.strip().lower()
        if not raw:
            return default
        return raw in ("y", "ya", "yes", "1", "true")

    def _read(self, prompt: str) -> str | None:
        """`input()` dengan sentinel None untuk EOF/Ctrl+C."""
        try:
            return input(prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
            raise ExitMenu()

    # -- pemilih -----------------------------------------------------------
    def select(self, prompt: str, options: Sequence[Option], *,
               default: str | None = None, allow_cancel: bool = True,
               filterable: bool = True) -> str | None:
        """Pilih satu opsi; return `Option.key` (None bila dibatalkan)."""
        if not options:
            return None
        if self.mode == "ptk":
            picked = self._ptk_select(prompt, options, default, allow_cancel, filterable)
            if picked is not False:
                return picked
            # False = ptk gagal -> lanjut ke plain
        return self._plain_select(prompt, options, default, allow_cancel)

    def _plain_select(self, prompt: str, options: Sequence[Option], default,
                      allow_cancel: bool, filterable: bool = True) -> str | None:
        self.install_completer([o.key for o in options] + [o.label for o in options])
        pool = list(options)
        shown = pool[:_PLAIN_PAGE]
        while True:
            for opt in shown:
                mark = self.style(opt.key.rjust(3), "cyan", "bold")
                detail = f"  {self.style(opt.detail, 'dim')}" if opt.detail else ""
                print(f"   {mark}  {opt.label}{detail}")
            if len(pool) > len(shown):
                print(self.style(f"   … {len(pool) - len(shown)} lainnya "
                                 "(ketik nama untuk mempersempit)", "dim"))
            hint = "  (q=batal)" if allow_cancel else ""
            raw = self._read(f"  {prompt}{hint}: ")
            if raw is None:
                if allow_cancel:
                    return None
                raise ExitMenu()
            value = raw.strip()
            if not value and default:
                return default
            if allow_cancel and value.lower() in ("q", "batal", "exit"):
                return None
            if not value:
                continue
            match = self._match_option(value, pool)
            if match:
                return match
            # Bukan nomor/label: anggap pencarian, persempit daftar.
            if filterable:
                narrowed = [o for o in pool if value.lower() in o.label.lower()
                            or value.lower() in o.detail.lower()]
                if narrowed:
                    pool = narrowed
                    shown = pool[:_PLAIN_PAGE]
                    continue
            self.warn("pilihan tidak dikenal, coba lagi")

    @staticmethod
    def _match_option(value: str, options: Sequence[Option]) -> str | None:
        low = value.lower()
        for opt in options:
            if low == opt.key.lower() or low == opt.label.lower():
                return opt.key
        for opt in options:
            if opt.label.lower().startswith(low) or low in opt.label.lower():
                return opt.key
        return None

    def multi(self, prompt: str, options: Sequence[Option], *,
              preselected: Iterable[str] = ()) -> list[str]:
        """Pilih banyak opsi (channel). Return list key (kosong = batal)."""
        if self.mode == "ptk":
            picked = self._ptk_multi(prompt, options, tuple(preselected))
            if picked is not False:
                return list(picked)
        self.install_completer([o.key for o in options] + [o.label for o in options])
        print(f"  {prompt} — pisahkan dengan koma, contoh: 1,3,5")
        for i, opt in enumerate(options, 1):
            print(f"   {i:3d}. {opt.label}" + (f"  {self.style(opt.detail, 'dim')}" if opt.detail else ""))
        raw = self._read("  nomor: ")
        if raw is None:
            raise ExitMenu()
        chosen: list[str] = []
        for token in raw.replace(" ", "").split(","):
            if not token:
                continue
            if token.isdigit():
                idx = int(token)
                if 1 <= idx <= len(options):
                    chosen.append(options[idx - 1].key)
                continue
            match = self._match_option(token, options)
            if match:
                chosen.append(match)
        return chosen

    # -- prompt_toolkit ----------------------------------------------------
    def _ptk_select(self, prompt: str, options: Sequence[Option], default,
                    allow_cancel: bool, filterable: bool):
        """Return key / None (batal) / False (ptk gagal -> fallback plain).

        `KeyboardInterrupt` (Ctrl+C) TIDAK ditelan: diteruskan ke menu supaya
        keluar dengan kode 130, bukan kembali ke menu.
        """
        try:
            key = _ptk_picker(prompt, options, default, allow_cancel, filterable)
        except KeyboardInterrupt:
            raise
        except ExitMenu:
            raise
        except Exception:
            return False
        return key

    def _ptk_multi(self, prompt: str, options: Sequence[Option], preselected: Sequence[str]):
        try:
            keys = _ptk_multi_picker(prompt, options, preselected)
        except KeyboardInterrupt:
            raise
        except ExitMenu:
            raise
        except Exception:
            return False
        return keys

    # -- readline ----------------------------------------------------------
    def install_completer(self, words: Sequence[str]) -> None:
        """Tab-completion sederhana (tanpa dependensi)."""
        if self.mode == "pipe" or self._completer_installed:
            return
        try:
            import readline
        except Exception:
            return
        pool = sorted({w for w in words if w})

        def _complete(text: str, state: int):
            hits = [w for w in pool if w.lower().startswith(text.lower())]
            return hits[state] if state < len(hits) else None

        try:
            readline.set_completer(_complete)
            readline.parse_and_bind("tab: complete")
            self._completer_installed = True
        except Exception:
            pass

    def load_history(self, path) -> None:
        if self.mode == "pipe":
            return
        try:
            import readline
            if path and os.path.isfile(path):
                readline.read_history_file(str(path))
        except Exception:
            pass

    def save_history(self, path) -> None:
        if self.mode == "pipe":
            return
        try:
            import readline
            if path:
                readline.write_history_file(str(path))
        except Exception:
            pass

    def pause(self, message: str = "Enter untuk lanjut") -> None:
        if self.mode == "pipe":
            return
        try:
            input(f"\n  {self.style('·', 'dim')} {message}...")
        except (EOFError, KeyboardInterrupt):
            raise ExitMenu()

    # -- tabel sederhana ---------------------------------------------------
    def table(self, rows: Sequence[Sequence[str]], *, headers: Sequence[str] = (),
              gap: int = 2) -> None:
        if not rows:
            return
        cols = len(rows[0])
        widths = [0] * cols
        for row in ([headers] if headers else []) + list(rows):
            for i, cell in enumerate(row[:cols]):
                widths[i] = max(widths[i], len(str(cell)))
        for i, w in enumerate(widths):
            widths[i] = min(w, max(8, self.width // max(1, cols)))
        if headers:
            head = (" " * gap).join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
            print("  " + self.style(head, "bold"))
            rule_ch = "─" if self.unicode else "-"
            print("  " + self.style(rule_ch * min(self.width - 2, sum(widths) + gap * (cols - 1)), "dim"))
        for row in rows:
            cells = []
            for i, cell in enumerate(row[:cols]):
                text = str(cell)
                if len(text) > widths[i]:
                    text = text[: max(1, widths[i] - 1)] + ("…" if self.unicode else "~")
                cells.append(text.ljust(widths[i]))
            print("  " + (" " * gap).join(cells))

# ---------------------------------------------------------------------------
# prompt_toolkit picker (diimpor malas; modul ini tetap ringan)
# ---------------------------------------------------------------------------
def _ptk_picker(prompt: str, options: Sequence[Option], default,
                allow_cancel: bool, filterable: bool):
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = {"filter": "", "index": 0, "offset": 0}
    view = 10

    def visible():
        needle = state["filter"].lower()
        if not needle:
            return list(options)
        return [o for o in options
                if needle in o.label.lower() or needle in o.detail.lower() or needle in o.key.lower()]

    def render():
        items = visible()
        if items:
            state["index"] = min(state["index"], len(items) - 1)
        else:
            state["index"] = 0
        if state["index"] < state["offset"]:
            state["offset"] = state["index"]
        elif state["index"] >= state["offset"] + view:
            state["offset"] = state["index"] - view + 1
        lines = [("class:title", f"  {prompt}\n")]
        if filterable:
            lines.append(("class:filter", f"  filter: {state['filter'] or '—'}\n"))
        if not items:
            lines.append(("class:dim", "  (tidak ada yang cocok)\n"))
        for i, opt in enumerate(items[state["offset"]: state["offset"] + view],
                                 start=state["offset"]):
            selected = i == state["index"]
            pointer = "▸ " if selected else "  "
            style = "class:selected" if selected else "class:item"
            detail = f"  {opt.detail}" if opt.detail else ""
            lines.append((style, f" {pointer}{opt.label}{detail}\n"))
        total = len(items)
        shown = min(view, total)
        lines.append(("class:dim",
                      f"\n  ↑↓ pilih · ketik=cari · backspace hapus · Enter=ok"
                      f"{' · Esc=batal' if allow_cancel else ''}"
                      f"   [{shown}/{total}]\n"))
        return FormattedText(lines)

    control = FormattedTextControl(render, focusable=True)
    window = Window(content=control, height=view + 4, wrap_lines=False)
    app = Application(
        layout=Layout(window),
        key_bindings=_ptk_keys(state, visible, allow_cancel, filterable),
        style=Style.from_dict({
            "title": "bold cyan",
            "filter": "yellow",
            "selected": "reverse bold",
            "item": "",
            "dim": "gray",
        }),
        full_screen=False,
    )

    if default:
        items = list(options)
        for i, opt in enumerate(items):
            if opt.key == default:
                state["index"] = i
                break

    result = app.run()
    return result

def _ptk_keys(state, visible, allow_cancel: bool, filterable: bool):
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @kb.add(Keys.Down)
    @kb.add("c-n")
    def _down(event):
        state["index"] += 1
        items = visible()
        if items:
            state["index"] %= len(items)
        event.app.invalidate()

    @kb.add(Keys.Up)
    @kb.add("c-p")
    def _up(event):
        items = visible()
        if items:
            state["index"] = (state["index"] - 1) % len(items)
        event.app.invalidate()

    @kb.add(Keys.PageDown)
    def _pgdn(event):
        state["index"] += 5
        event.app.invalidate()

    @kb.add(Keys.PageUp)
    def _pgup(event):
        state["index"] = max(0, state["index"] - 5)
        event.app.invalidate()

    @kb.add(Keys.Enter)
    def _enter(event):
        items = visible()
        if not items:
            return
        state["index"] = min(state["index"], len(items) - 1)
        event.app.exit(result=items[state["index"]].key)

    @kb.add(Keys.Escape)
    def _cancel(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def _interrupt(event):
        event.app.exit(exception=KeyboardInterrupt())

    @kb.add("c-q")
    def _quit(event):
        event.app.exit(result=None)

    @kb.add(Keys.Backspace)
    def _backspace(event):
        if filterable and state["filter"]:
            state["filter"] = state["filter"][:-1]
            state["index"] = 0
            event.app.invalidate()

    @kb.add(Keys.Any)
    def _any(event):
        if not filterable:
            return
        data = event.data or ""
        if data.isprintable() and data.strip():
            state["filter"] += data
            state["index"] = 0
            event.app.invalidate()

    return kb

def _ptk_multi_picker(prompt: str, options: Sequence[Option], preselected: Sequence[str]):
    """Multi-pilih sederhana: checkbox + filter, Enter=selesai."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = {"filter": "", "index": 0, "offset": 0,
             "checked": set(preselected)}
    view = 10

    def visible():
        needle = state["filter"].lower()
        if not needle:
            return list(options)
        return [o for o in options if needle in o.label.lower() or needle in o.key.lower()]

    def render():
        items = visible()
        state["index"] = min(state["index"], max(0, len(items) - 1))
        if state["index"] < state["offset"]:
            state["offset"] = state["index"]
        elif state["index"] >= state["offset"] + view:
            state["offset"] = state["index"] - view + 1
        lines = [("class:title", f"  {prompt}  (spasi=pilih, Enter=selesai)\n"),
                 ("class:filter", f"  filter: {state['filter'] or '—'}\n")]
        for i, opt in enumerate(items[state["offset"]: state["offset"] + view],
                                 start=state["offset"]):
            cursor = "▸ " if i == state["index"] else "  "
            mark = "[x]" if opt.key in state["checked"] else "[ ]"
            style = "class:selected" if i == state["index"] else "class:item"
            lines.append((style, f" {cursor}{mark} {opt.label}"
                                  + (f"  {opt.detail}" if opt.detail else "") + "\n"))
        lines.append(("class:dim", f"\n  terpilih: {len(state['checked'])}"
                                   f" · ↑↓ · spasi · ketik=cari · Enter=selesai\n"))
        return FormattedText(lines)

    kb = KeyBindings()

    @kb.add(Keys.Down)
    @kb.add("c-n")
    def _down(event):
        items = visible()
        if items:
            state["index"] = (state["index"] + 1) % len(items)
        event.app.invalidate()

    @kb.add(Keys.Up)
    @kb.add("c-p")
    def _up(event):
        items = visible()
        if items:
            state["index"] = (state["index"] - 1) % len(items)
        event.app.invalidate()

    @kb.add(Keys.Space)
    def _toggle(event):
        items = visible()
        if not items:
            return
        key = items[min(state["index"], len(items) - 1)].key
        state["checked"].symmetric_difference_update({key})
        event.app.invalidate()

    @kb.add(Keys.Enter)
    def _enter(event):
        event.app.exit(result=sorted(state["checked"]))

    @kb.add(Keys.Escape)
    def _cancel(event):
        event.app.exit(result=[])

    @kb.add("c-c")
    def _interrupt(event):
        event.app.exit(exception=KeyboardInterrupt())

    @kb.add(Keys.Backspace)
    def _backspace(event):
        if state["filter"]:
            state["filter"] = state["filter"][:-1]
            state["index"] = 0
            event.app.invalidate()

    @kb.add(Keys.Any)
    def _any(event):
        data = event.data or ""
        if data.isprintable() and data.strip():
            state["filter"] += data
            state["index"] = 0
            event.app.invalidate()

    app = Application(
        layout=Layout(Window(content=FormattedTextControl(render, focusable=True),
                             height=view + 5, wrap_lines=False)),
        key_bindings=kb,
        style=Style.from_dict({"title": "bold cyan", "filter": "yellow",
                               "selected": "reverse bold", "item": "", "dim": "gray"}),
        full_screen=False,
    )
    result = app.run()
    return list(result or [])
