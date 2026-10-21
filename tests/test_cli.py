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
from contextlib import redirect_stderr, redirect_stdout
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
                rc = cli.main(["analyze", "--video", "gAQIEyzUHYc", "--lang", "id", "--json"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["video_id"], "gAQIEyzUHYc")
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
                rc = cli.main(["analyze", "--video", "gAQIEyzUHYc", "--lang", "id"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("video      : gAQIEyzUHYc", text)
        self.assertIn("kasta      :", text)

    def test_analyze_accepts_url(self):
        import cs_core.transcript as transcript

        seen = {}

        def fake(video_id, *a, **k):
            seen["id"] = video_id
            return [{"sec": 0, "text": "cegukan"}], "mock", "hit"

        orig = transcript.get_segments
        transcript.get_segments = fake
        try:
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["analyze", "--video",
                               "https://www.youtube.com/watch?v=gAQIEyzUHYc&t=5",
                               "--lang", "id", "--json"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        self.assertEqual(seen["id"], "gAQIEyzUHYc")

    def test_analyze_rejects_bad_id(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli.main(["analyze", "--video", "bukan-id", "--lang", "id"])
        self.assertEqual(rc, int(cli.ExitCode.USAGE))

    def test_analyze_multiple_videos_returns_array(self):
        import cs_core.transcript as transcript

        orig = transcript.get_segments
        transcript.get_segments = lambda *a, **k: ([{"sec": 0, "text": "cegukan"}], "mock", "hit")
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli.main(["analyze", "--video", "gAQIEyzUHYc,8jPQjjsBbIc",
                               "--lang", "id", "--json"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertIsInstance(payload, list)
        self.assertEqual([p["video_id"] for p in payload],
                         ["gAQIEyzUHYc", "8jPQjjsBbIc"])

    def test_analyze_partial_failure_keeps_successes(self):
        import cs_core.transcript as transcript

        from cs_core.errors import TranscriptUnavailable

        def fake(video_id, *a, **k):
            if video_id == "8jPQjjsBbIc":
                raise TranscriptUnavailable("tidak ada transkrip")
            return [{"sec": 0, "text": "cegukan"}], "mock", "hit"

        orig = transcript.get_segments
        transcript.get_segments = fake
        try:
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                rc = cli.main(["analyze", "--video", "gAQIEyzUHYc",
                               "--video", "8jPQjjsBbIc", "--lang", "id", "--json"])
        finally:
            transcript.get_segments = orig

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual([p["video_id"] for p in payload], ["gAQIEyzUHYc"])

    def test_analyze_from_file(self):
        import cs_core.transcript as transcript

        orig = transcript.get_segments
        transcript.get_segments = lambda *a, **k: ([{"sec": 0, "text": "cegukan"}], "mock", "hit")
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "vids.txt"
            listing.write_text(
                "# komentar\nhttps://youtu.be/gAQIEyzUHYc\n\n"
                "https://www.youtube.com/watch?v=8jPQjjsBbIc&t=9\n",
                encoding="utf-8",
            )
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = cli.main(["analyze", "--from-file", str(listing),
                                   "--lang", "id", "--json"])
            finally:
                transcript.get_segments = orig

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual([p["video_id"] for p in payload],
                         ["gAQIEyzUHYc", "8jPQjjsBbIc"])

class TestCacheJsonPlacement(unittest.TestCase):
    """`--json` harus diterima sebelum MAUPUN sesudah subcommand."""

    def _stats(self, argv):
        r = subprocess.run([sys.executable, "-m", "cs_core", *argv],
                           capture_output=True, text=True, cwd=str(REPO_ROOT))
        return r, json.loads(r.stdout)

    def test_json_after_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, payload = self._stats(["cache", "--cache-dir", tmp, "stats", "--json"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(payload["files"], 0)

    def test_json_before_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, payload = self._stats(["cache", "--cache-dir", tmp, "--json", "stats"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(payload["files"], 0)

class TestEnginePreflight(unittest.TestCase):
    """Engine yang butuh binary eksternal harus gagal cepat dengan exit 4."""

    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "cs_core", *args],
                              capture_output=True, text=True, cwd=str(REPO_ROOT))

    def test_age_reports_missing_ytdlp(self):
        import shutil as _shutil

        if _shutil.which("yt-dlp"):
            self.skipTest("yt-dlp terpasang di lingkungan ini")
        r = self._run("age", "--channel", "x", "--no-prompt")
        self.assertEqual(r.returncode, int(cli.ExitCode.DEPENDENCY))
        self.assertIn("yt-dlp", r.stderr)
        self.assertIn("doctor --fix", r.stderr)
        # Pesan saran generik tidak boleh muncul menimpa penyebab sebenarnya.
        self.assertNotIn("cek nama channel", r.stderr)

    def test_index_reports_missing_ytdlp(self):
        import shutil as _shutil

        if _shutil.which("yt-dlp"):
            self.skipTest("yt-dlp terpasang di lingkungan ini")
        r = self._run("index", "--channel", "x", "--no-prompt")
        self.assertEqual(r.returncode, int(cli.ExitCode.DEPENDENCY))
        self.assertIn("yt-dlp", r.stderr)

    def test_scan_reports_missing_ytdlp(self):
        import shutil as _shutil

        if _shutil.which("yt-dlp"):
            self.skipTest("yt-dlp terpasang di lingkungan ini")
        r = self._run("scan", "--channel", "x", "--limit", "1")
        self.assertEqual(r.returncode, int(cli.ExitCode.DEPENDENCY))
        self.assertIn("yt-dlp", r.stderr)
        self.assertNotIn("cek nama channel", r.stderr)

class TestReportCommand(unittest.TestCase):
    def test_list_json_on_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, "-m", "cs_core", "report", "--dir", tmp, "list", "--json"],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), [])

    def test_rm_keep_zero(self):
        from cs_core import reports

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for i, name in enumerate(("a", "b")):
                path = reports.report_path(name, folder=folder)
                path.write_text("x", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, "-m", "cs_core", "report", "--dir", tmp,
                 "rm", "--keep", "0", "--json"],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["removed"], 2)
            self.assertEqual(reports.list_reports(folder), [])

    def test_open_missing_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, "-m", "cs_core", "report", "--dir", tmp, "open", "tidak-ada"],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
            )
            self.assertEqual(r.returncode, int(cli.ExitCode.USAGE))
            self.assertIn("tidak ditemukan", r.stderr)

if __name__ == "__main__":
    unittest.main()
