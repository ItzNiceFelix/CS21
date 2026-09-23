#!/usr/bin/env python3
"""Test menu interaktif cs_core (tanpa network, tanpa TTY)."""

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

from cs_core import cli, menu  # noqa: E402


class TestSavedChannels(unittest.TestCase):
    def test_remember_and_load_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu.remember_channel("windahbasudara", tmp)
            menu.remember_channel("@Afandix", tmp)
            menu.remember_channel("windahbasudara", tmp)
            # Isolasi: channels.txt saja (abaikan checkpoint/index_cache HOME).
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


class TestMenuLoop(unittest.TestCase):
    def _run_menu(self, inputs, config_dir="."):
        it = iter(inputs)
        orig_input = builtins.input
        orig_clear = menu._clear
        menu._clear = lambda: None

        def _fake_input(*a, **k):
            try:
                return next(it)
            except StopIteration:
                raise EOFError()  # stdin habis (mis. cron/pipe)

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
        rc, out = self._run_menu(["0"])
        self.assertEqual(rc, 0)
        self.assertIn("sampai jumpa", out)

    def test_invalid_then_quit(self):
        rc, out = self._run_menu(["x", "0"])
        self.assertEqual(rc, 0)
        self.assertIn("tak valid", out)

    def test_eof_exits_cleanly(self):
        rc, out = self._run_menu([])
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
            rc = cli.main([])
        finally:
            menu_mod.run_menu = orig
        self.assertEqual(rc, 0)
        self.assertTrue(called.get("hit"))


if __name__ == "__main__":
    unittest.main()
