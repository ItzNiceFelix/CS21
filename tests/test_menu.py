#!/usr/bin/env python3
"""Menu interaktif cs_core — perilaku (tanpa network, tanpa TTY)."""

from __future__ import annotations

import builtins
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core import menu  # noqa: E402
from cs_core.tui import UI, ExitMenu  # noqa: E402

class TestSavedChannels(unittest.TestCase):
    def test_remember_and_load_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu.remember_channel("windahbasudara", tmp)
            menu.remember_channel("@Afandix", tmp)
            menu.remember_channel("windahbasudara", tmp)
            txt = (Path(tmp) / "channels.txt").read_text(encoding="utf-8").split()
            self.assertEqual(txt, ["windahbasudara", "Afandix"])
            loaded = menu.load_saved_channels(tmp)
            self.assertEqual(loaded[:2], ["windahbasudara", "Afandix"])
            self.assertEqual(loaded.count("windahbasudara"), 1)

    def test_load_from_checkpoint_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = Path(tmp) / "checkpoints"
            cp.mkdir(parents=True)
            (cp / "canalA.checkpoint").write_text("DONE=1\n", encoding="utf-8")
            self.assertIn("canalA", menu.load_saved_channels(tmp))

class TestChannelNormalization(unittest.TestCase):
    def test_strips_url_and_at(self):
        for raw, want in (
            ("@windahbasudara", "windahbasudara"),
            ("https://www.youtube.com/@Afandix/videos", "Afandix"),
            ("youtube.com/c/FooBar", "FooBar"),
            ("channel/UCabc", "UCabc"),
            ("  windah basudara ", "windahbasudara"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(menu._normalize_channel(raw), want)

    def test_video_id_from_url(self):
        for raw, want in (
            ("gAQIEyzUHYc", "gAQIEyzUHYc"),
            ("https://www.youtube.com/watch?v=gAQIEyzUHYc", "gAQIEyzUHYc"),
            ("https://youtu.be/gAQIEyzUHYc?t=30", "gAQIEyzUHYc"),
            ("too-short", ""),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(menu._video_id(raw), want)

class TestMenuLoop(unittest.TestCase):
    def _run_menu(self, inputs, config_dir):
        it = iter(inputs)
        orig_input = builtins.input
        orig_clear = menu._clear
        menu._clear = lambda: None

        def _fake_input(*a, **k):
            try:
                return next(it)
            except StopIteration:
                raise EOFError()

        builtins.input = _fake_input
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                rc = menu.run_menu(config_dir=config_dir, lang="id")
        finally:
            builtins.input = orig_input
            menu._clear = orig_clear
        return rc, out.getvalue()

    def test_quit_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run_menu(["0"], tmp)
            self.assertEqual(rc, 0)
            self.assertIn("sampai jumpa", out)

    def test_invalid_choice_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run_menu(["zzz", "0"], tmp)
            self.assertEqual(rc, 0)
            self.assertIn("sampai jumpa", out)

    def test_eof_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run_menu([], tmp)
            self.assertEqual(rc, 0)
            self.assertIn("input berakhir", out)

class TestNoArgsOpensMenu(unittest.TestCase):
    def test_no_subcommand_routes_to_menu(self):
        called = {}
        import cs_core.menu as menu_mod
        orig = menu_mod.run_menu

        def _fake_run_menu(**k):
            called["hit"] = True
            return 0

        menu_mod.run_menu = _fake_run_menu
        try:
            from cs_core import cli
            rc = cli.main([])
        finally:
            menu_mod.run_menu = orig
        self.assertEqual(rc, 0)
        self.assertTrue(called.get("hit"))

class TestPlainSelect(unittest.TestCase):
    """UI.select di mode plain harus menerima nomor, nama, dan q=batal."""

    def _ui(self):
        return UI(interactive=True, colors=False, width=60, mode="plain")

    def _feed(self, values):
        it = iter(values)
        orig = builtins.input
        builtins.input = lambda *a, **k: next(it)
        return orig

    def test_select_by_number_and_cancel(self):
        from cs_core.tui import Option

        opts = [Option("1", "scan"), Option("2", "analyze")]
        ui = self._ui()
        orig = self._feed(["2"])
        try:
            self.assertEqual(ui.select("pilih", opts), "2")
        finally:
            builtins.input = orig

        orig = self._feed(["q"])
        try:
            self.assertIsNone(ui.select("pilih", opts))
        finally:
            builtins.input = orig

    def test_select_by_label(self):
        from cs_core.tui import Option

        opts = [Option("1", "scan channel"), Option("2", "analyze video")]
        ui = self._ui()
        orig = self._feed(["analyze"])
        try:
            self.assertEqual(ui.select("pilih", opts), "2")
        finally:
            builtins.input = orig

    def test_eof_raises_exit_menu(self):
        from cs_core.tui import Option

        ui = self._ui()

        def _boom(*a, **k):
            raise EOFError()

        orig = builtins.input
        builtins.input = _boom
        try:
            with self.assertRaises(ExitMenu):
                ui.select("pilih", [Option("1", "x")], allow_cancel=False)
        finally:
            builtins.input = orig

if __name__ == "__main__":
    unittest.main()
