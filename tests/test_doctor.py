#!/usr/bin/env python3
"""`cs21 doctor` — preflight tanpa jaringan + bentuk output JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core import doctor  # noqa: E402

class TestCollect(unittest.TestCase):
    def test_offline_collect_has_no_network_check(self):
        rep = doctor.collect(check_network=False)
        names = [c.name for c in rep.checks]
        self.assertIn("jaringan", names)
        jaringan = next(c for c in rep.checks if c.name == "jaringan")
        self.assertEqual(jaringan.status, doctor.INFO)
        self.assertIn("offline", jaringan.detail)

    def test_core_checks_present(self):
        rep = doctor.collect(check_network=False)
        names = {c.name for c in rep.checks}
        for expected in ("python", "yt-dlp", "config-dir", "engine", "storage", "webhook"):
            self.assertIn(expected, names, expected)

    def test_engine_missing_is_fatal(self):
        """Folder repo palsu -> cek engine harus fatal (bukan crash)."""
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(doctor._settings, "repo_root", lambda: Path(tmp)):
                rep = doctor.collect(check_network=False)
        engine = next(c for c in rep.checks if c.name == "engine")
        self.assertEqual(engine.status, doctor.FATAL)
        self.assertTrue(engine.detail)

    def test_rapidfuzz_without_native_is_warned(self):
        from unittest import mock

        with mock.patch.object(doctor, "_probe_rapidfuzz", lambda: (True, False)):
            rep = doctor.collect(check_network=False)
        rf = next(c for c in rep.checks if c.name == "rapidfuzz")
        self.assertEqual(rf.status, doctor.WARN)
        self.assertTrue(rf.fixable)

    def test_rapidfuzz_absent_is_info(self):
        from unittest import mock

        with mock.patch.object(doctor, "_probe_rapidfuzz", lambda: (False, False)):
            rep = doctor.collect(check_network=False)
        rf = next(c for c in rep.checks if c.name == "rapidfuzz")
        self.assertEqual(rf.status, doctor.INFO)

class TestRunDoctor(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cs_core", "doctor", *args],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env=dict(os.environ),
        )

    def test_json_shape(self):
        r = self._run("--json")
        self.assertIn(r.returncode, (0, 1))
        payload = json.loads(r.stdout)
        self.assertIn("ok", payload)
        self.assertIn("checks", payload)
        self.assertTrue(payload["checks"])
        for entry in payload["checks"]:
            for key in ("name", "status", "detail"):
                self.assertIn(key, entry)

    def test_text_output_has_verdict_line(self):
        r = self._run()
        self.assertIn(r.returncode, (0, 1))
        self.assertIn("cs21 doctor", r.stdout)
        self.assertTrue(
            any(marker in r.stdout for marker in
                ("semua siap", "peringatan", "masalah fatal")),
            r.stdout[-400:],
        )

class TestFixGuards(unittest.TestCase):
    def test_cookies_fix_requires_terminal(self):
        check = doctor.Check("cookies", doctor.WARN, "belum ada", fix="bash setup_cookies.sh",
                             fixable=True)
        ok, note = doctor._apply_fix(check, interactive=False)
        self.assertFalse(ok)
        self.assertIn("butuh terminal", note)

    def test_unknown_check_has_no_fix(self):
        check = doctor.Check("misteri", doctor.WARN, "x")
        ok, note = doctor._apply_fix(check, interactive=False)
        self.assertFalse(ok)
        self.assertIn("tidak ada perbaikan", note)

if __name__ == "__main__":
    unittest.main()
