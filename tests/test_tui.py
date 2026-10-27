#!/usr/bin/env python3
"""Lapisan UI: pemilihan backend, lebar adaptif, dan fallback tanpa
`prompt_toolkit`. Tidak butuh TTY nyata."""

from __future__ import annotations

import builtins
import importlib
import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core.tui import ExitMenu, Option, UI  # noqa: E402
import cs_core.tui as tui  # noqa: E402

def _feed(values):
    it = iter(values)

    def _fake(*a, **k):
        try:
            return next(it)
        except StopIteration:
            raise EOFError()

    return mock.patch.object(builtins, "input", _fake)

class TestModeSelection(unittest.TestCase):
    def test_non_tty_forces_pipe(self):
        ui = UI(interactive=False, mode="auto")
        self.assertEqual(ui.mode, "pipe")

    def test_plain_when_requested(self):
        ui = UI(interactive=True, mode="plain")
        self.assertEqual(ui.mode, "plain")

    def test_ptk_when_available(self):
        ui = UI(interactive=True, mode="ptk")
        self.assertIn(ui.mode, ("ptk", "plain"))

    def test_missing_prompt_toolkit_falls_back(self):
        import cs_core.tui as tui

        with mock.patch.object(tui, "_HAVE_PTK", False):
            ui = UI(interactive=True, mode="auto")
            self.assertEqual(ui.mode, "plain")

class TestWidth(unittest.TestCase):
    def test_narrow_terminal_is_bounded(self):
        ui = UI(interactive=True, mode="plain", width=30)
        self.assertEqual(ui.width, 30)

    def test_minimum_width_enforced(self):
        """Di bawah 24 kolom tata letak rusak -> dipaksa 24."""
        self.assertEqual(UI(interactive=True, mode="plain", width=10).width, 24)

    def test_explicit_width_is_respected(self):
        """Override eksplisit dipakai apa adanya (dipakai test/tangkapan layar)."""
        self.assertEqual(UI(interactive=True, mode="plain", width=500).width, 500)

    def test_detected_width_is_clamped(self):
        import cs_core.tui as tui

        ui = UI(interactive=True, mode="plain")
        with mock.patch.object(tui.shutil, "get_terminal_size",
                               lambda *a, **k: __import__("os").terminal_size((500, 40))):
            self.assertEqual(ui.width, 100)
        with mock.patch.object(tui.shutil, "get_terminal_size",
                               lambda *a, **k: __import__("os").terminal_size((10, 40))):
            self.assertEqual(ui.width, 24)

    def test_rule_matches_width(self):
        ui = UI(interactive=True, colors=False, mode="plain", width=40)
        out = io.StringIO()
        with redirect_stdout(out):
            ui.rule()
        line = out.getvalue().strip()
        self.assertEqual(len(line), 40)

    def test_title_never_exceeds_width(self):
        """Regresi: judul panjang tidak boleh melebihi lebar terminal."""
        for width in (24, 40, 80, 100):
            with self.subTest(width=width):
                ui = UI(interactive=True, colors=False, mode="plain", width=width)
                out = io.StringIO()
                with redirect_stdout(out):
                    ui.title("CS21 · Cegukan Seeker V21")
                line = out.getvalue().rstrip("\n")
                self.assertLessEqual(len(line), width, line)

class TestColors(unittest.TestCase):
    def test_colors_off_has_no_escape(self):
        ui = UI(interactive=True, colors=False, mode="plain")
        self.assertEqual(ui.style("halo", "red", "bold"), "halo")

    def test_colors_on_wraps(self):
        ui = UI(interactive=True, colors=True, mode="plain")
        self.assertIn("\033[", ui.style("halo", "red"))

class TestPlainSelect(unittest.TestCase):
    def _ui(self, **kw):
        return UI(interactive=True, colors=False, mode="plain", width=60, **kw)

    def test_number_and_label(self):
        opts = [Option("1", "scan channel"), Option("2", "analisa video")]
        ui = self._ui()
        with _feed(["1"]):
            self.assertEqual(ui.select("pilih", opts), "1")
        with _feed(["analisa"]):
            self.assertEqual(ui.select("pilih", opts), "2")

    def test_filter_narrows_then_selects(self):
        """Ketik sebagian nama -> daftar menyempit -> pilih nomornya."""
        opts = [Option(str(i), f"channel-{i}") for i in range(1, 40)]
        opts.append(Option("99", "Afandix"))
        ui = self._ui()
        with _feed(["afan", "1"]):
            self.assertEqual(ui.select("pilih channel", opts), "99")

    def test_long_list_is_paged(self):
        opts = [Option(str(i), f"ch-{i}") for i in range(1, 60)]
        ui = self._ui()
        out = io.StringIO()
        with _feed(["3"]), redirect_stdout(out):
            self.assertEqual(ui.select("pilih", opts), "3")
        text = out.getvalue()
        self.assertIn("lainnya", text)
        self.assertLess(text.count("\n"), 30, "daftar panjang tidak boleh di-dump penuh")

    def test_cancel_returns_none(self):
        ui = self._ui()
        with _feed(["q"]):
            self.assertIsNone(ui.select("pilih", [Option("1", "x")]))

    def test_eof_raises_exit_menu_when_cancel_not_allowed(self):
        ui = self._ui()
        with _feed([]):
            with self.assertRaises(ExitMenu):
                ui.select("pilih", [Option("1", "x")], allow_cancel=False)

    def test_unknown_input_reprompts(self):
        ui = self._ui()
        out = io.StringIO()
        with _feed(["ngawur", "1"]), redirect_stdout(out):
            self.assertEqual(ui.select("pilih", [Option("1", "x")]), "1")
        self.assertIn("tidak dikenal", out.getvalue())

class TestAskAndConfirm(unittest.TestCase):
    def _ui(self):
        return UI(interactive=True, colors=False, mode="plain", width=60)

    def test_default_used_on_empty(self):
        ui = self._ui()
        with _feed([""]):
            self.assertEqual(ui.ask("limit", default="20"), "20")

    def test_validate_reprompts(self):
        ui = self._ui()
        seen = []

        def _validate(value):
            seen.append(value)
            return None if value.isdigit() else "harus angka"

        with _feed(["abc", "7"]):
            self.assertEqual(ui.ask("limit", validate=_validate), "7")
        self.assertEqual(seen, ["abc", "7"])

    def test_confirm_variants(self):
        ui = self._ui()
        for raw, expected in (("y", True), ("ya", True), ("n", False), ("", False)):
            with self.subTest(raw=raw), _feed([raw]):
                self.assertEqual(ui.confirm("lanjut?"), expected)

    def test_confirm_default_true(self):
        ui = self._ui()
        with _feed([""]):
            self.assertTrue(ui.confirm("lanjut?", default=True))

class TestMulti(unittest.TestCase):
    def test_comma_separated_numbers(self):
        ui = UI(interactive=True, colors=False, mode="plain", width=60)
        opts = [Option("a", "satu"), Option("b", "dua"), Option("c", "tiga")]
        with _feed(["1,3"]):
            self.assertEqual(ui.multi("pilih channel", opts), ["a", "c"])

    def test_unknown_tokens_ignored(self):
        ui = UI(interactive=True, colors=False, mode="plain", width=60)
        opts = [Option("a", "satu")]
        with _feed(["1,zzz"]):
            self.assertEqual(ui.multi("pilih", opts), ["a"])

class TestTable(unittest.TestCase):
    def test_table_aligns_and_truncates(self):
        ui = UI(interactive=True, colors=False, mode="plain", width=40)
        out = io.StringIO()
        with redirect_stdout(out):
            ui.table([["a", "x" * 80], ["bb", "y"]], headers=["key", "value"])
        lines = [l for l in out.getvalue().splitlines() if l.strip()]
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertLessEqual(len(line), 45)

class _FakeReader:
    """`_KeyReader` palsu: kembalikan tombol dari daftar, tanpa terminal."""

    def __init__(self, keys):
        self._keys = list(keys)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def key(self):
        return self._keys.pop(0)

class TestRawPick(unittest.TestCase):
    """Pemilih raw: panah + filter langsung tanpa `prompt_toolkit`."""

    def _pick(self, options, keys, **kw):
        ui = UI(interactive=True, colors=False, mode="plain", width=80)
        with mock.patch.object(tui, "_raw_capable", lambda: True), \
                mock.patch.object(tui, "_KeyReader", lambda: _FakeReader(keys)):
            out = io.StringIO()
            with redirect_stdout(out):
                result = ui.pick("pilih", options, **kw)
        return result, out.getvalue()

    def test_typing_filters_then_enter_selects(self):
        opts = [Option("1", "channel-satu"), Option("2", "channel-dua"),
                Option("3", "Afandix")]
        result, out = self._pick(
            opts, [("char", "a"), ("char", "f"), ("char", "a"), ("enter", "")])
        self.assertEqual(result, "3")
        self.assertIn("filter: afa", out)

    def test_arrow_keys_move_selection(self):
        opts = [Option("1", "satu"), Option("2", "dua"), Option("3", "tiga")]
        result, _ = self._pick(opts, [("down", ""), ("down", ""), ("enter", "")])
        self.assertEqual(result, "3")

    def test_pinned_option_survives_filter(self):
        opts = [Option("0", "➕ Channel baru", pinned=True),
                Option("1", "alpha"), Option("2", "beta")]
        result, _ = self._pick(opts, [("char", "z"), ("enter", "")])
        self.assertEqual(result, "0")

    def test_typing_number_then_enter_selects_that_key(self):
        opts = [Option("1", "satu"), Option("2", "dua")]
        result, _ = self._pick(opts, [("char", "2"), ("enter", "")])
        self.assertEqual(result, "2")

    def test_multi_toggles_with_space(self):
        opts = [Option("a", "satu"), Option("b", "dua")]
        keys = [("space", ""), ("down", ""), ("space", ""), ("enter", "")]
        result, _ = self._pick(opts, keys, multi=True)
        self.assertEqual(result, ["a", "b"])

    def test_escape_cancels(self):
        result, _ = self._pick([Option("1", "satu")], [("esc", "")])
        self.assertIsNone(result)

    def test_direct_key_without_filter(self):
        opts = [Option("1", "satu"), Option("2", "dua")]
        result, _ = self._pick(opts, [("char", "2")], filterable=False)
        self.assertEqual(result, "2")

class TestKeyReader(unittest.TestCase):
    """Parsing tombol terminal: panah datang sebagai escape sequence."""

    def _read(self, chunks):
        reader = tui._KeyReader()
        reader._fd = 0
        it = iter(chunks)

        def _read_byte(fd, n):
            try:
                return next(it)
            except StopIteration:
                return b""

        with mock.patch("os.read", _read_byte), \
                mock.patch("select.select", return_value=([0], [], [])):
            return reader._key_posix()

    def test_arrow_sequences(self):
        for seq, want in ((b"\x1b[A", "up"), (b"\x1b[B", "down"),
                          (b"\x1b[5~", "pgup"), (b"\x1b[6~", "pgdn")):
            with self.subTest(seq=seq):
                self.assertEqual(self._read([seq[:1], seq[1:2], seq[2:]]), (want, ""))

    def test_lone_escape_is_cancel(self):
        reader = tui._KeyReader()
        reader._fd = 0
        with mock.patch("os.read", lambda fd, n: b"\x1b"), \
                mock.patch("select.select", return_value=([], [], [])):
            self.assertEqual(reader._key_posix(), ("esc", ""))

    def test_enter_and_backspace(self):
        self.assertEqual(self._read([b"\r"]), ("enter", ""))
        self.assertEqual(self._read([b"\x7f"]), ("backspace", ""))
        self.assertEqual(self._read([b"a"]), ("char", "a"))

if __name__ == "__main__":
    unittest.main()
