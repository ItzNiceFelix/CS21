#!/usr/bin/env python3
"""Delegasi menu -> engine lama: argumen HARUS lengkap (regresi menu 5/6/7/8).

Dulu menu memanggil engine hanya dengan `--config-dir` + `--lang`, sehingga
argparse engine langsung gagal (`--channel`/`--checkpoint-dir` wajib).
Test ini mengunci kontrak itu tanpa menjalankan engine sungguhan.
"""

from __future__ import annotations

import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cs_core import menu  # noqa: E402
from cs_core.tui import UI  # noqa: E402

def _ctx(tmp: str, lang: str = "id") -> menu.Ctx:
    cfg = Path(tmp)
    cfg.mkdir(parents=True, exist_ok=True)
    ui = UI(interactive=True, colors=False, width=70, mode="plain")
    from cs_core import settings as st

    return menu.Ctx(ui=ui, config_dir=cfg, lang=lang,
                    settings=st.Settings(lang=lang), executor="Tester")

def _feed(values):
    it = iter(values)

    def _fake(*a, **k):
        try:
            return next(it)
        except StopIteration:
            raise EOFError()

    return mock.patch.object(builtins, "input", _fake)

def _captured_run():
    """Ganti `menu._run_engine`; kembalikan dict hasil tangkapan."""
    box: dict = {}

    def _fake(ctx, name, args, **kw):
        box["name"] = name
        box["args"] = list(args)
        box["label"] = kw.get("label", "")
        return 0

    return box, mock.patch.object(menu, "_run_engine", _fake)

class TestScanDelegation(unittest.TestCase):
    def test_scan_args_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            (Path(tmp) / "channels.txt").write_text("Afandix\n", encoding="utf-8")
            box, patcher = _captured_run()
            with patcher, _feed(["1", "5", "n"]):
                menu._act_scan(ctx)
            args = box["args"]
            self.assertEqual(box["name"], "scan")
            for flag in ("--channel", "--limit", "--jobs", "--mode", "--config-dir",
                         "--checkpoint-dir", "--lang", "--executor"):
                self.assertIn(flag, args, flag)
            self.assertEqual(args[args.index("--channel") + 1], "Afandix")
            self.assertEqual(args[args.index("--mode") + 1], "plain")

class TestIndexDelegation(unittest.TestCase):
    def test_index_args_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            (Path(tmp) / "channels.txt").write_text("channelA\n", encoding="utf-8")
            box, patcher = _captured_run()
            # pilih channel 1, total video 100, batch 10, per-run 2, jobs 2, konfirmasi y
            with patcher, _feed(["1", "100", "10", "2", "2", "y"]):
                menu._act_index(ctx)
            args = box["args"]
            self.assertEqual(box["name"], "index")
            for flag in ("--channel", "--total-videos", "--total-batches",
                         "--batches-per-run", "--start-batch", "--config-dir",
                         "--lang", "--jobs", "--executor", "--no-prompt"):
                self.assertIn(flag, args, flag)
            self.assertEqual(args[args.index("--total-videos") + 1], "100")
            self.assertEqual(args[args.index("--total-batches") + 1], "10")
            self.assertEqual(args[args.index("--start-batch") + 1], "1")

class TestAgeDelegation(unittest.TestCase):
    def test_age_args_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            box, patcher = _captured_run()
            # pilih "_new" -> ketik channel, konten semua, limit 5, lanjut tanpa cookies
            with patcher, _feed(["_new", "channelB", "1", "5", "y"]):
                menu._act_age(ctx)
            args = box["args"]
            self.assertEqual(box["name"], "age")
            for flag in ("--channel", "--lang", "--content-type", "--limit",
                         "--config-dir", "--jobs", "--no-prompt"):
                self.assertIn(flag, args, flag)
            self.assertEqual(args[args.index("--channel") + 1], "channelB")
            self.assertEqual(args[args.index("--content-type") + 1], "all")

class TestAutodriveDelegation(unittest.TestCase):
    def test_autodrive_args_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            box, patcher = _captured_run()
            with patcher, _feed(["1", "10", "0", ""]):
                menu._act_autodrive(ctx)
            args = box["args"]
            self.assertEqual(box["name"], "autodrive")
            for flag in ("--lang", "--time-range", "--limit-per-channel",
                         "--max-cycles", "--config-dir", "--checkpoint-dir"):
                self.assertIn(flag, args, flag)

class TestBlockedDelegation(unittest.TestCase):
    def test_retry_uses_blocked_log(self):
        import json as _json

        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            log = Path(tmp) / "channelC_blocked.json"
            log.write_text(_json.dumps({
                "channel": "channelC",
                "videos": [{"id": "abc12345678", "reason": "RequestBlocked"}],
            }), encoding="utf-8")
            box, patcher = _captured_run()
            with patcher, _feed(["channelC", "y"]):
                menu._act_blocked(ctx)
            args = box["args"]
            self.assertEqual(box["name"], "scan")
            self.assertEqual(args[args.index("--channel") + 1], "channelC")
            self.assertEqual(args[args.index("--retry-blocked-log") + 1], str(log))

class TestWebhookArgs(unittest.TestCase):
    def test_webhook_selected_by_lang(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp, lang="id")
            (Path(tmp) / ".webhook_injected").write_text(
                'WEBHOOK_INDONESIA="https://id.example/hook"\n'
                'WEBHOOK_GLOBAL="https://global.example/hook"\n',
                encoding="utf-8",
            )
            self.assertEqual(menu._webhook_args(ctx),
                             ["--webhook-url", "https://id.example/hook"])
            ctx.lang = "en"
            self.assertEqual(menu._webhook_args(ctx),
                             ["--webhook-url", "https://global.example/hook"])

    def test_no_webhook_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            with mock.patch.dict("os.environ", {"CS_WEBHOOK": ""}, clear=False):
                self.assertEqual(menu._webhook_args(ctx), [])

class TestChatseekerGuard(unittest.TestCase):
    def test_non_interactive_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(tmp)
            ctx.ui.interactive = False
            ctx.ui.mode = "pipe"
            box, patcher = _captured_run()
            with patcher:
                menu._act_chatseeker(ctx)
            self.assertNotIn("name", box, "ChatSeeker tidak boleh dipanggil dari pipe")

if __name__ == "__main__":
    unittest.main()
