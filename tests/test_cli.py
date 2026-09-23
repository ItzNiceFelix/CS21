#!/usr/bin/env python3
"""Fase 7 — smoke test CLI `python -m cs_core` (tanpa network).

- `--help` exit 0 tanpa deps berat.
- `cache stats` jalan di cache-dir sementara.
- `analyze` dengan transcript di-mock (tanpa network) -> kasta + JSON valid.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core import cli  # noqa: E402


def _run_module(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "cs_core", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


class TestCliHelp(unittest.TestCase):
    def test_help_exit_zero_no_heavy_deps(self):
        r = _run_module("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for cmd in ("scan", "analyze", "search", "index", "age", "cache"):
            self.assertIn(cmd, r.stdout)

    def test_subcommand_help(self):
        for cmd in ("scan", "analyze", "search", "cache"):
            with self.subTest(cmd=cmd):
                r = _run_module(cmd, "--help")
                self.assertEqual(r.returncode, 0, r.stderr)


class TestCliCache(unittest.TestCase):
    def test_cache_stats_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["cache", "--cache-dir", tmp, "stats"])
            self.assertEqual(rc, 0)
            self.assertIn("files     : 0", out.getvalue())

    def test_cache_purge_all(self):
        from cs_core import cache

        with tempfile.TemporaryDirectory() as tmp:
            cache.write("abc", "id", [{"sec": 0, "text": "cegukan"}], source="t", root=tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["cache", "--cache-dir", tmp, "purge", "--all"])
            self.assertEqual(rc, 0)
            self.assertIn("purge: 1 file", out.getvalue())


class TestCliAnalyze(unittest.TestCase):
    def test_analyze_json_mock(self):
        """Mock transcript.get_segments -> tak butuh network/deps."""
        import cs_core.transcript as transcript

        segments = [
            {"sec": 0, "text": "cegukan"},
            {"sec": 60, "text": "cegukan lagi"},
            {"sec": 120, "text": "halo biasa"},
        ]
        orig = transcript.get_segments
        transcript.get_segments = lambda *a, **k: (segments, "mock", "hit")
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["analyze", "--video", "abc", "--lang", "id", "--json"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["video_id"], "abc")
        self.assertGreater(payload["tier_counts"]["CORE"], 0)
        self.assertEqual(payload["source"], "mock")


class TestCliScan(unittest.TestCase):
    def test_scan_requires_channel(self):
        out = io.StringIO()
        err = io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["scan", "--channel", "  "])
        self.assertEqual(rc, 2)
        self.assertIn("--channel wajib", err.getvalue())

    def test_scan_builds_plain_passthrough(self):
        """scan tanpa --ui harus memanggil engine dengan --mode plain."""
        captured = {}
        orig = cli._run_engine
        cli._run_engine = lambda script, args: captured.update(script=script, args=args) or 0
        try:
            rc = cli.main(["scan", "--channel", "UCabc", "--limit", "3",
                           "--config-dir", "cfg", "--checkpoint-dir", "cp"])
        finally:
            cli._run_engine = orig
        self.assertEqual(rc, 0)
        self.assertEqual(captured["script"], "cs20_engine.py")
        args = captured["args"]
        self.assertIn("--mode", args)
        self.assertEqual(args[args.index("--mode") + 1], "plain")
        self.assertIn("UCabc", args)

    def test_scan_ui_uses_pantau(self):
        captured = {}
        orig = cli._run_engine
        cli._run_engine = lambda script, args: captured.update(args=args) or 0
        try:
            cli.main(["scan", "--channel", "UCabc", "--ui"])
        finally:
            cli._run_engine = orig
        args = captured["args"]
        self.assertEqual(args[args.index("--mode") + 1], "pantau")


if __name__ == "__main__":
    unittest.main()
