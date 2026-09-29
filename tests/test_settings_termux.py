#!/usr/bin/env python3
"""Preferensi persisten + integrasi Termux (tanpa perangkat nyata)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core import settings as S  # noqa: E402
from cs_core import termux as T  # noqa: E402

class TestSettings(unittest.TestCase):
    def test_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = S.load(tmp)
            self.assertEqual(s.lang, "id")
            self.assertEqual(s.fuzzy, "auto")
            self.assertGreaterEqual(s.jobs, 1)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            S.update(tmp, lang="jp", jobs=7, fuzzy="on", limit=99, last_channel="Afandix")
            again = S.load(tmp)
            self.assertEqual((again.lang, again.fuzzy, again.jobs, again.limit,
                              again.last_channel), ("jp", "on", 7, 99, "Afandix"))

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "settings.json").write_text("{rusak", encoding="utf-8")
            self.assertEqual(S.load(tmp).jobs, S.Settings().jobs)

    def test_out_of_range_values_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            S.update(tmp, jobs=999, limit=-5, fuzzy="ngawur", ui="xxx")
            s = S.load(tmp)
            self.assertLessEqual(s.jobs, 16)
            self.assertGreaterEqual(s.limit, 0)
            self.assertEqual(s.fuzzy, "auto")
            self.assertEqual(s.ui, "auto")

    def test_config_dir_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "cfg"
            path = S.config_dir(target)
            self.assertTrue(path.is_dir())
            self.assertTrue(S.settings_path(target).parent.is_dir())

class TestTermuxGuards(unittest.TestCase):
    def test_missing_binary_is_false_not_raise(self):
        T._UNAVAILABLE.clear()
        self.assertFalse(T._run(["binary-yang-tidak-ada-xyz"]))

    def test_failure_is_cached(self):
        T._UNAVAILABLE.clear()
        with mock.patch.object(T, "have", lambda name: True), \
             mock.patch.object(T.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1)
            self.assertFalse(T.notify("a", "b"))
            self.assertFalse(T.notify("a", "b"))
            self.assertEqual(run.call_count, 1, "kegagalan harus di-cache")

    def test_success_path(self):
        T._UNAVAILABLE.clear()
        with mock.patch.object(T, "have", lambda name: True), \
             mock.patch.object(T.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.assertTrue(T.wake_lock())

    def test_wake_lock_ctx_unlocks_on_error(self):
        calls = []

        def _fake_lock():
            calls.append("lock")
            return True

        def _fake_unlock():
            calls.append("unlock")
            return True

        with mock.patch.object(T, "wake_lock", _fake_lock), \
             mock.patch.object(T, "wake_unlock", _fake_unlock):
            with self.assertRaises(RuntimeError):
                with T.wake_lock_ctx():
                    raise RuntimeError("boom")
        self.assertEqual(calls, ["lock", "unlock"])

    def test_open_file_missing_is_false(self):
        self.assertFalse(T.open_file("/tidak/ada/file.html"))

    def test_suggest_jobs_bounds(self):
        for ram, expected in ((0, 4), (200, 2), (600, 3), (1200, 4), (4000, 6)):
            with self.subTest(ram=ram):
                with mock.patch.object(T, "ram_available_mb", lambda r=ram: r):
                    self.assertEqual(T.suggest_jobs(), expected)

if __name__ == "__main__":
    unittest.main()
