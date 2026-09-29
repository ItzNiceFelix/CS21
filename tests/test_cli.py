#!/usr/bin/env python3
"""Smoke test CLI `cs21` — jalur yang tidak butuh jaringan.

Kontrak exit code & pesan error ada di `tests/test_errors.py`; menu di
`tests/test_menu.py`; delegasi engine di `tests/test_menu_delegation.py`.
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

class TestStartupIsLight(unittest.TestCase):
    """`--help`/`--version` tidak boleh menarik yt-dlp/rich/requests."""

    def test_help_exit_zero(self):
        r = _run_module("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for cmd in ("menu", "scan", "analyze", "search", "index", "age", "cache", "doctor"):
            self.assertIn(cmd, r.stdout)

    def test_help_does_not_import_heavy_deps(self):
        probe = (
            "import sys, io, contextlib;"
            "buf=io.StringIO();"
            "from cs_core import cli;"
            "code=0\n"
            "with contextlib.redirect_stdout(buf):\n"
            "    try:\n"
            "        code = cli.main(['--help'])\n"
            "    except SystemExit as e:\n"
            "        code = e.code or 0\n"
            "heavy=[m for m in ('yt_dlp','rich','requests','youtube_transcript_api')\n"
            "       if m in sys.modules]\n"
            "print('HEAVY', heavy, 'CODE', code)\n"
        )
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                           text=True, cwd=str(REPO_ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HEAVY []", r.stdout)

class TestCacheCommands(unittest.TestCase):
    def test_stats_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["cache", "--cache-dir", tmp, "stats"])
            self.assertEqual(rc, 0)
            self.assertIn("files     : 0", out.getvalue())

    def test_purge_all_removes_files(self):
        from cs_core import cache

        with tempfile.TemporaryDirectory() as tmp:
            cache.write("abc", "id", [{"sec": 0, "text": "cegukan"}], source="t", root=tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["cache", "--cache-dir", tmp, "purge", "--all"])
            self.assertEqual(rc, 0)
            self.assertIn("purge: 1 file", out.getvalue())
            self.assertEqual(list(Path(tmp).rglob("*.jsonl.gz")), [])

    def test_gc_keeps_fresh_files(self):
        from cs_core import cache

        with tempfile.TemporaryDirectory() as tmp:
            cache.write("abc", "id", [{"sec": 0, "text": "cegukan"}], source="t", root=tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["cache", "--cache-dir", tmp, "gc"])
            self.assertEqual(rc, 0)
            self.assertEqual(len(list(Path(tmp).rglob("*.jsonl.gz"))), 1)

class TestAnalyzeWithoutNetwork(unittest.TestCase):
    def test_analyze_json_with_mocked_transcript(self):
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

    def test_analyze_summary_is_human_readable(self):
        import cs_core.transcript as transcript

        segments = [{"sec": 0, "text": "cegukan"}]
        orig = transcript.get_segments
        transcript.get_segments = lambda *a, **k: (segments, "mock", "hit")
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["analyze", "--video", "abc", "--lang", "id"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("video      : abc", text)
        self.assertIn("kasta      :", text)

if __name__ == "__main__":
    unittest.main()
