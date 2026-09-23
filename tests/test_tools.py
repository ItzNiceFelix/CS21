#!/usr/bin/env python3
"""Fase 0 — test tools (stdlib unittest).

Jalan via: python -m unittest discover -s tests -v
Kompatibel pytest (tak wajib).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import baseline_compare, fixtures_synthetic  # noqa: E402

TOOLS_DIR = REPO_ROOT / "tools"


def _run_tool(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS_DIR / name), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _sample_doc() -> dict:
    return {
        "meta": {
            "channel": "test",
            "lang": "id",
            "dedup_mode": "baseline",
            "cluster_mode": "baseline",
        },
        "videos": [
            {
                "video_id": "abc",
                "source": "yt-api",
                "segments_raw": [{"sec": 0, "text": "cegukan"}],
                "engines": {"e": {"score": 5, "kasta": "VALID"}},
            }
        ],
    }


class TestBaselineCompare(unittest.TestCase):
    def test_self_compare_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            path.write_text(json.dumps(_sample_doc()), encoding="utf-8")
            self.assertEqual(baseline_compare.compare(str(path), str(path)), 0)

    def test_two_identical_files_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = json.dumps(_sample_doc())
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text(doc, encoding="utf-8")
            b.write_text(doc, encoding="utf-8")
            self.assertEqual(baseline_compare.compare(str(a), str(b)), 0)

    def test_diff_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text(json.dumps(_sample_doc()), encoding="utf-8")
            other = _sample_doc()
            other["videos"][0]["engines"]["e"]["score"] = 99
            b.write_text(json.dumps(other), encoding="utf-8")
            self.assertEqual(baseline_compare.compare(str(a), str(b)), 1)

    def test_ignore_fields_suppresses_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            base = _sample_doc()
            base["videos"][0]["engines"]["e"]["html_rows"] = "<tr>A</tr>"
            other = _sample_doc()
            other["videos"][0]["engines"]["e"]["html_rows"] = "<tr>B</tr>"
            a.write_text(json.dumps(base), encoding="utf-8")
            b.write_text(json.dumps(other), encoding="utf-8")
            self.assertEqual(baseline_compare.compare(str(a), str(b)), 1)
            self.assertEqual(
                baseline_compare.compare(str(a), str(b), ("html_rows",)), 0
            )


class TestToolHelp(unittest.TestCase):
    def test_baseline_capture_help_exit_zero(self):
        r = _run_tool("baseline_capture.py", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--channel", r.stdout)

    def test_baseline_compare_help_exit_zero(self):
        r = _run_tool("baseline_compare.py", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_fixtures_synthetic_help_exit_zero(self):
        r = _run_tool("fixtures_synthetic.py", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_baseline_capture_dry_run_exit_zero(self):
        # --dry-run harus jalan tanpa yt-dlp / rich (PC ini).
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dry.json"
            r = _run_tool(
                "baseline_capture.py", "--dry-run", "--out", str(out), "--channel", "x"
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(doc["meta"]["dedup_mode"], "baseline")
            self.assertEqual(doc["meta"]["cluster_mode"], "baseline")
            self.assertEqual(doc["videos"], [])


class TestFixturesSynthetic(unittest.TestCase):
    def test_document_structure(self):
        doc = fixtures_synthetic.build_document()
        self.assertIn("meta", doc)
        self.assertIn("cases", doc)
        self.assertIn("segments", doc)
        self.assertEqual(doc["meta"]["dedup_mode"], "baseline")
        expected = {
            "zero_core",
            "maraton_single_cluster",
            "multisisi",
            "silent_treatment",
            "dedup_float",
            "typo_asr",
        }
        self.assertTrue(expected.issubset(set(doc["cases"])))
        for name, case in doc["cases"].items():
            self.assertIn("segments", case, name)
            self.assertTrue(case["segments"], name)
            for seg in case["segments"]:
                self.assertIsInstance(seg["sec"], int)
                self.assertIsInstance(seg["text"], str)

    def test_writes_valid_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "synth.json"
            r = _run_tool("fixtures_synthetic.py", "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(doc["cases"]), 6)

    def test_dedup_float_case_has_same_sec(self):
        doc = fixtures_synthetic.build_document()
        segs = doc["cases"]["dedup_float"]["segments"]
        same = [s for s in segs if s["sec"] == 120]
        self.assertEqual(len(same), 2)
        self.assertNotEqual(same[0].get("duration"), same[1].get("duration"))


if __name__ == "__main__":
    unittest.main()
