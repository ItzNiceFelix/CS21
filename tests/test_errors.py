#!/usr/bin/env python3
"""Kontrak error & exit code CLI (`cs_core.errors`, `cs_core.cli`).

Fokus: hal-hal yang bisa dilihat user/script —
exit code benar, pesan satu baris berbahasa Indonesia, dan stdout murni
saat `--json` (tidak tercemar peringatan dependensi).
"""

from __future__ import annotations

import io
import json
import os
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
from cs_core.errors import (  # noqa: E402
    ExitCode,
    UsageError,
    describe_transcript_error,
    first_line,
    resolve_lang,
)

def _run(*args: str, env: dict | None = None, cwd: str | None = None):
    merged = dict(os.environ)
    merged.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "cs_core", *args],
        capture_output=True, text=True, cwd=cwd or str(REPO_ROOT), env=merged,
    )

class TestResolveLang(unittest.TestCase):
    def test_valid_and_alias(self):
        self.assertEqual(resolve_lang("id"), "id")
        self.assertEqual(resolve_lang(""), "id")
        self.assertEqual(resolve_lang("ja"), "jp")
        self.assertEqual(resolve_lang("KO"), "kr")
        self.assertEqual(resolve_lang("hi"), "in")
        self.assertEqual(resolve_lang("id-ID"), "id")

    def test_invalid_raises_usage(self):
        with self.assertRaises(UsageError) as ctx:
            resolve_lang("xx")
        self.assertEqual(ctx.exception.code, ExitCode.USAGE)
        self.assertIn("tidak dikenal", ctx.exception.message)
        self.assertIn("id, en, jp, kr, in, th", ctx.exception.hint)

class TestFirstLine(unittest.TestCase):
    def test_skips_leading_blank_lines(self):
        self.assertEqual(first_line("\n\n  halo dunia \nlanjut"), "halo dunia")
        self.assertEqual(first_line(""), "")

class TestDescribeTranscriptError(unittest.TestCase):
    def test_known_reason_uses_indonesian(self):
        class VideoUnavailable(Exception):
            pass

        err = describe_transcript_error(VideoUnavailable("The video is no longer available"),
                                        "abc12345678")
        self.assertIn("abc12345678", err.message)
        self.assertIn("tidak tersedia", err.message)
        self.assertNotIn("no longer available", err.message)
        self.assertTrue(err.hint)

    def test_reason_found_through_wrapped_cause(self):
        class TranscriptsDisabled(Exception):
            pass

        try:
            try:
                raise TranscriptsDisabled("x")
            except TranscriptsDisabled as inner:
                raise RuntimeError("dibungkus") from inner
        except RuntimeError as wrapped:
            err = describe_transcript_error(wrapped, "vid")
        self.assertIn("dinonaktifkan", err.message)

    def test_unknown_reason_falls_back_to_first_line(self):
        err = describe_transcript_error(RuntimeError("\n  ada yang aneh  \ndetail"),
                                        "vid")
        self.assertIn("ada yang aneh", err.message)
        self.assertNotIn("\n", err.message)

class TestCliExitCodes(unittest.TestCase):
    def test_unknown_subcommand_is_usage_error(self):
        r = _run("frobnicate")
        self.assertEqual(r.returncode, int(ExitCode.USAGE))

    def test_missing_required_arg_is_usage_error(self):
        r = _run("scan")
        self.assertEqual(r.returncode, int(ExitCode.USAGE))

    def test_invalid_lang_rejected_without_creating_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run("analyze", "--video", "gAQIEyzUHYc", "--lang", "xx",
                     "--cache-dir", tmp)
            self.assertEqual(r.returncode, int(ExitCode.USAGE))
            self.assertIn("tidak dikenal", r.stderr)
            leftovers = list(Path(tmp).rglob("*.jsonl.gz"))
            self.assertEqual(leftovers, [], "cache tidak boleh dibuat untuk bahasa invalid")

    def test_search_missing_index_dir_is_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "tidak-ada")
            r = _run("search", "--query", "cegukan", "--index-dir", missing)
            self.assertEqual(r.returncode, int(ExitCode.FAIL))
            self.assertIn("tidak ditemukan", r.stderr)

    def test_search_empty_index_dir_is_success(self):
        """Folder index kosong = belum ada hasil, bukan error."""
        with tempfile.TemporaryDirectory() as tmp:
            r = _run("search", "--query", "cegukan", "--index-dir", tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("tak ada hasil", r.stdout)

class TestJsonPurity(unittest.TestCase):
    """stdout harus JSON murni walau ada peringatan storage/dependensi."""

    def _fake_home(self, tmp: str) -> dict:
        return {"HOME": tmp}

    def test_search_json_stdout_is_clean(self):
        with tempfile.TemporaryDirectory() as home:
            index_dir = Path(home) / "idx"
            index_dir.mkdir()
            r = _run("search", "--query", "cegukan", "--index-dir", str(index_dir),
                     "--json", env=self._fake_home(home))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), [])

    def test_cache_stats_json_stdout_is_clean(self):
        with tempfile.TemporaryDirectory() as home:
            r = _run("cache", "--cache-dir", home, "stats", "--json",
                     env=self._fake_home(home))
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["files"], 0)
            self.assertIn("dir", payload)

    def test_analyze_json_error_keeps_stdout_empty(self):
        """Error tidak boleh mengotori stdout saat --json."""
        r = _run("analyze", "--video", "zzzzzzzzzzz", "--lang", "id", "--json",
                 env={"HOME": tempfile.mkdtemp()})
        if r.returncode == 0:  # jaringan sangat lambat -> skip
            self.skipTest("fetch tidak gagal seperti yang diharapkan")
        self.assertEqual(r.stdout.strip(), "")
        self.assertTrue(r.stderr.strip())

class TestCliScanPassthrough(unittest.TestCase):
    def test_scan_normalizes_channel_and_uses_plain(self):
        captured = {}
        orig = cli._run_engine

        def _fake(script, args, **kw):
            captured.update(script=script, args=args, kw=kw)
            return 0

        cli._run_engine = _fake
        try:
            with tempfile.TemporaryDirectory() as tmp:
                rc = cli.main(["scan", "--channel", "@windahbasudara", "--limit", "3",
                               "--config-dir", tmp, "--checkpoint-dir", str(Path(tmp) / "cp")])
        finally:
            cli._run_engine = orig
        self.assertEqual(rc, 0)
        args = captured["args"]
        self.assertEqual(captured["script"], "cs20_engine.py")
        self.assertEqual(args[args.index("--mode") + 1], "plain")
        self.assertEqual(args[args.index("--channel") + 1], "windahbasudara")
        self.assertNotIn("@@", " ".join(args))

    def test_scan_json_keeps_engine_output_off_stdout(self):
        captured = {}
        orig = cli._run_engine

        def _fake(script, args, **kw):
            captured.update(kw)
            return 0

        cli._run_engine = _fake
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = io.StringIO()
                with redirect_stdout(out):
                    rc = cli.main(["scan", "--channel", "UCabc", "--json",
                                   "--config-dir", tmp,
                                   "--checkpoint-dir", str(Path(tmp) / "cp")])
        finally:
            cli._run_engine = orig
        self.assertEqual(rc, 0)
        self.assertTrue(captured.get("quiet_stdout"))
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["channel"], "UCabc")

    def test_scan_ui_uses_pantau(self):
        captured = {}
        orig = cli._run_engine

        def _fake(script, args, **kw):
            captured.update(args=args)
            return 0

        cli._run_engine = _fake
        try:
            cli.main(["scan", "--channel", "UCabc", "--ui"])
        finally:
            cli._run_engine = orig
        args = captured["args"]
        self.assertEqual(args[args.index("--mode") + 1], "pantau")

    def test_scan_propagates_engine_failure(self):
        orig = cli._run_engine
        cli._run_engine = lambda script, args, **kw: 1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                rc = cli.main(["scan", "--channel", "nope",
                               "--config-dir", tmp, "--checkpoint-dir", tmp])
        finally:
            cli._run_engine = orig
        self.assertEqual(rc, 1)

class TestCliHelp(unittest.TestCase):
    def test_help_lists_all_commands(self):
        r = _run("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for cmd in ("menu", "scan", "analyze", "search", "index", "age", "cache", "doctor"):
            self.assertIn(cmd, r.stdout)

    def test_subcommand_help(self):
        for cmd in ("scan", "analyze", "search", "cache", "doctor", "menu"):
            with self.subTest(cmd=cmd):
                r = _run(cmd, "--help")
                self.assertEqual(r.returncode, 0, r.stderr)

if __name__ == "__main__":
    unittest.main()
