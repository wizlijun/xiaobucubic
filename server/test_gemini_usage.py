import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import display_server
import gemini_usage


def sample_payload(
    weekly_remaining=0.9957584142684937,
    five_hour_remaining=0.9876362681388855,
    weekly_reset="2026-12-02T04:22:08Z",
    five_hour_reset="2026-11-25T09:22:08Z",
    groups=None,
    status="SUCCESS",
):
    if groups is None:
        groups = [
            {
                "name": "Gemini Models",
                "description": "Models within this group: Gemini 4 Neon, Gemini 3.8 Flash",
                "buckets": [
                    {
                        "id": "gemini-weekly",
                        "name": "Weekly Limit Remaining",
                        "window": "weekly",
                        "remaining_fraction": weekly_remaining,
                        "reset_time": weekly_reset,
                    },
                    {
                        "id": "gemini-5h",
                        "name": "Five Hour Limit Remaining",
                        "window": "5h",
                        "remaining_fraction": five_hour_remaining,
                        "reset_time": five_hour_reset,
                    },
                ],
            },
            {
                "name": "Claude and GPT models",
                "buckets": [
                    {
                        "id": "3p-weekly",
                        "name": "Weekly Limit Remaining",
                        "window": "weekly",
                        "remaining_fraction": 0.2,
                        "reset_time": "2026-12-02T04:27:42Z",
                    },
                    {
                        "id": "3p-5h",
                        "name": "Five Hour Limit Remaining",
                        "window": "5h",
                        "remaining_fraction": 0.1,
                        "reset_time": "2026-11-25T09:27:42Z",
                    },
                ],
            },
        ]
    return {
        "conversation_id": "",
        "status": status,
        "response": "",
        "duration_seconds": 0,
        "num_turns": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
        },
        "command": {
            "name": "usage",
            "data": {
                "groups": groups,
            },
        },
    }


class GeminiUsageTests(unittest.TestCase):
    def test_to_display_orders_5h_first_then_weekly_and_matches_server_schema(self):
        payload = sample_payload()
        item = gemini_usage.to_display(payload)
        self.assertEqual(item["id"], "gemini")
        self.assertEqual(item["name"], "Gemini")
        self.assertEqual(item["source"], "official")
        self.assertEqual(len(item["windows"]), 2)
        self.assertEqual(item["windows"][0], {
            "label": "5小时",
            "used_percent": 1.2,
            "reset_at": 1795598528,
        })
        self.assertEqual(item["windows"][1], {
            "label": "7天",
            "used_percent": 0.4,
            "reset_at": 1796185328,
        })
        self.assertEqual(display_server.clean_subscription("gemini", item, item["updated_at"]), item)

    def test_boundary_remaining_fractions(self):
        for frac, expected_used in ((1, 0), (1.0, 0), (0, 100), (0.0, 100), (0.5, 50), (0.665, 33.5), (0.9999, 0)):
            with self.subTest(frac=frac):
                self.assertEqual(gemini_usage.remaining_to_used_percent(frac), expected_used)

    def test_invalid_remaining_fractions_raise(self):
        for bad in (True, False, -0.01, 1.01, float("nan"), float("inf"), "0.5", []):
            with self.subTest(bad=bad):
                with self.assertRaises(RuntimeError):
                    gemini_usage.remaining_to_used_percent(bad)

    def test_find_gemini_group_falls_back_to_group_name(self):
        payload = sample_payload(groups=[
            {
                "name": "Other Models",
                "buckets": [{"id": "other-5h", "window": "5h", "remaining_fraction": 0.1}],
            },
            {
                "name": "Google Gemini Tier",
                "buckets": [{"id": "tier-5h", "window": "5h", "remaining_fraction": 0.75}],
            },
        ])
        item = gemini_usage.to_display(payload)
        self.assertEqual(item["windows"], [{"label": "5小时", "used_percent": 25, "reset_at": None}])

    def test_missing_gemini_group_or_empty_buckets_raises(self):
        for groups in ([], [{"name": "Claude and GPT models", "buckets": [{"id": "3p-5h", "remaining_fraction": 1}]}],
                       [{"name": "Gemini Models", "buckets": []}],
                       [{"name": "Gemini Models", "buckets": [{"id": "gemini-5h", "remaining_fraction": None}]}]):
            with self.subTest(groups=groups):
                with self.assertRaises(RuntimeError):
                    gemini_usage.to_display(sample_payload(groups=groups))

    def test_fetch_usage_invokes_agy_readonly_usage_command(self):
        payload = sample_payload()
        completed = subprocess.CompletedProcess(
            args=["/usr/local/bin/agy", "--print", "/usage", "--output-format", "json"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        with patch.object(gemini_usage, "resolve_agy_bin", return_value="/usr/local/bin/agy"), \
                patch.object(gemini_usage.subprocess, "run", return_value=completed) as run:
            result = gemini_usage.fetch_usage(timeout=25)
        self.assertEqual(result, payload)
        run.assert_called_once_with(
            ["/usr/local/bin/agy", "--print", "/usage", "--output-format", "json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
        )

    def test_fetch_usage_errors(self):
        with patch.object(gemini_usage, "resolve_agy_bin", return_value="/bin/agy"):
            with patch.object(gemini_usage.subprocess, "run", side_effect=subprocess.TimeoutExpired("agy", 10)):
                with self.assertRaisesRegex(RuntimeError, "超时"):
                    gemini_usage.fetch_usage(timeout=10)

            failed = subprocess.CompletedProcess(["/bin/agy"], 1, stdout="", stderr="auth required\n")
            with patch.object(gemini_usage.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "退出码 1.*auth required"):
                    gemini_usage.fetch_usage()

            bad_json = subprocess.CompletedProcess(["/bin/agy"], 0, stdout="not json", stderr="")
            with patch.object(gemini_usage.subprocess, "run", return_value=bad_json):
                with self.assertRaisesRegex(RuntimeError, "JSON"):
                    gemini_usage.fetch_usage()

            bad_status = subprocess.CompletedProcess(
                ["/bin/agy"], 0, stdout=json.dumps(sample_payload(status="ERROR")), stderr=""
            )
            with patch.object(gemini_usage.subprocess, "run", return_value=bad_status):
                with self.assertRaisesRegex(RuntimeError, "异常状态"):
                    gemini_usage.fetch_usage()

    def test_resolve_agy_bin_prefers_arg_env_path_then_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "agy"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            self.assertEqual(gemini_usage.resolve_agy_bin(str(fake)), str(fake))
            with patch.dict(os.environ, {"AGY_BIN": str(fake)}):
                self.assertEqual(gemini_usage.resolve_agy_bin(), str(fake))
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(gemini_usage.shutil, "which", return_value=None), \
                    patch.object(gemini_usage, "FALLBACK_AGY_PATHS", (str(fake),)):
                self.assertEqual(gemini_usage.resolve_agy_bin(), str(fake))
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(gemini_usage.shutil, "which", return_value=None), \
                    patch.object(gemini_usage, "FALLBACK_AGY_PATHS", (str(Path(tmp) / "missing"),)):
                with self.assertRaisesRegex(RuntimeError, "未找到 agy"):
                    gemini_usage.resolve_agy_bin()

    def test_print_usage_renders_human_readable_output(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gemini_usage.print_usage(sample_payload())
        output = buf.getvalue()
        self.assertIn("Gemini Models", output)
        self.assertIn("当前会话 (5 小时)", output)
        self.assertIn("本周 (7 天)", output)
        self.assertIn("剩余  98.8%", output)
        self.assertIn("剩余  99.6%", output)

    def test_display_server_registers_and_orders_gemini(self):
        self.assertEqual(display_server.COLLECTORS.get("gemini"), "gemini_usage.py")
        scheduler = display_server.Scheduler()
        self.assertIn("gemini", scheduler.sources)
        data = {
            "subscriptions": {
                "bandwagon": {"id": "bandwagon", "name": "Bandwagon", "source": "official", "updated_at": 100, "windows": []},
                "gemini": {"id": "gemini", "name": "Gemini", "source": "official", "updated_at": 100, "windows": []},
                "claude": {"id": "claude", "name": "Claude", "source": "official", "updated_at": 100, "windows": []},
                "grok": {"id": "grok", "name": "Grok", "source": "official", "updated_at": 100, "windows": []},
                "codex": {"id": "codex", "name": "Codex", "source": "official", "updated_at": 100, "windows": []},
            },
            "messages": [],
            "weather": None,
        }
        body = json.loads(display_server.build_display(data, 900, 100).decode("utf-8"))
        ids = [sub["id"] for sub in body["subscriptions"]]
        self.assertEqual(ids, ["claude", "codex", "grok", "gemini", "bandwagon"])


if __name__ == "__main__":
    unittest.main()
