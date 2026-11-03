import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import banwagong_usage as usage
import display_push
import display_server as server


GIB = 1024**3


def response(**changes):
    return dict({"error": 0, "plan_monthly_data": 1000 * GIB,
                 "data_counter": 250 * GIB, "monthly_data_multiplier": 1,
                 "data_next_reset": 1794009600, "plan": "test-plan"}, **changes)


class UsageTests(unittest.TestCase):
    def test_monthly_remaining_and_multiplier(self):
        for multiplier in (1, 0.5, 2, "0.333"):
            with self.subTest(multiplier=multiplier):
                data = response(monthly_data_multiplier=multiplier)
                data["plan_monthly_data"] = str(data["plan_monthly_data"])
                data["data_counter"] = str(data["data_counter"])
                data["data_next_reset"] = str(data["data_next_reset"])
                item = usage.to_display(data)
                w = item["windows"][0]
                self.assertEqual(item["id"], "banwagong")
                self.assertEqual(w["used_percent"], 25)
                self.assertEqual(w["total_bytes"], int(usage.Decimal(1000 * GIB) * usage.Decimal(str(multiplier))))
                self.assertEqual(w["remaining_bytes"], w["total_bytes"] - w["used_bytes"])
                self.assertEqual(w["reset_at"], 1794009600)
                self.assertEqual(server.clean_subscription("banwagong", item, 1), item)

    def test_missing_multiplier_defaults_to_one(self):
        data = response()
        del data["monthly_data_multiplier"]
        self.assertEqual(usage.to_display(data)["windows"][0]["remaining_bytes"], 750 * GIB)

    def test_unused_exhausted_and_over_quota(self):
        for used, pct, remaining in ((0, 0, 1000), (1000, 100, 0), (1100, 110, 0)):
            with self.subTest(used=used):
                w = usage.to_display(response(data_counter=used * GIB))["windows"][0]
                self.assertEqual(w["used_percent"], pct)
                self.assertEqual(w["remaining_bytes"], remaining * GIB)

    def test_reset_in_past_is_not_fabricated_new_cycle(self):
        w = usage.to_display(response(data_next_reset=100))["windows"][0]
        self.assertEqual(w["reset_at"], 100)
        self.assertEqual(w["used_bytes"], 250 * GIB)

    def test_invalid_data_does_not_become_zero_usage(self):
        for key in ("plan_monthly_data", "data_counter", "monthly_data_multiplier", "data_next_reset"):
            for value in (None, True, -1, "NaN", "Infinity", [], "bad", 10**100):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(RuntimeError):
                        usage.to_display(response(**{key: value}))
        for change in ({"plan_monthly_data": 0}, {"monthly_data_multiplier": 0},
                       {"data_next_reset": 0}, {"data_next_reset": 1794009600000},
                       {"data_counter": 0.5}, {"monthly_data_multiplier": 1e-30}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                usage.to_display(response(**change))

    def test_integer_byte_precision(self):
        w = usage.to_display(response(plan_monthly_data=2**53-1, data_counter=2**53-2))["windows"][0]
        self.assertEqual(w["remaining_bytes"], 1)
        self.assertEqual(server.clean_window(w)["remaining_bytes"], 1)

    def test_legacy_window_unchanged(self):
        w = {"label": "7天", "used_percent": 33.5, "reset_at": None}
        self.assertEqual(server.clean_window(w), w)

    def test_server_derives_percent_and_remaining(self):
        w = server.clean_window({"label": "月度", "total_bytes": 100, "used_bytes": 40,
                                 "used_percent": 1})
        self.assertEqual(w["used_percent"], 40)
        self.assertEqual(w["remaining_bytes"], 60)
        for change in ({"remaining_bytes": 61}, {"remaining_bytes": True},
                       {"used_bytes": 0.5}, {"used_bytes": -1}, {"total_bytes": 0},
                       {"total_bytes": 2**53}, {"total_bytes": None}):
            with self.subTest(change=change), self.assertRaises(server.BadRequest):
                server.clean_window(dict(w, **change))

    def test_credentials_file_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / "banwagong.env"
            with patch.object(usage, "ENV_FILE", path):
                self.assertIsNone(usage.load_credentials())
                path.write_text('# comment\nBANWAGONG_VEID=123\nBANWAGONG_API_KEY="file-key" # comment\n')
                self.assertEqual(usage.load_credentials(), ("123", "file-key"))
                with patch.dict(os.environ, {"BANWAGONG_API_KEY": "env-key"}):
                    self.assertEqual(usage.load_credentials(), ("123", "env-key"))
                path.write_text('BANWAGONG_VEID=123\n')
                with self.assertRaises(RuntimeError):
                    usage.load_credentials()

    def test_unconfigured_push_skips_without_writing(self):
        with patch.object(usage, "load_credentials", return_value=None), \
                patch.object(display_push, "push") as push, \
                patch.object(sys, "argv", ["banwagong_usage.py", "--push"]), \
                contextlib.redirect_stdout(io.StringIO()):
            usage.main()
            push.assert_not_called()

    def test_post_uses_body_and_fixed_endpoint(self):
        with patch.object(urllib.request, "build_opener") as build:
            build.return_value.open.return_value = io.BytesIO(json.dumps(response()).encode())
            self.assertEqual(usage.fetch_usage("123", "private-test"), response())
            req = build.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, usage.API_URL)
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(urllib.parse.parse_qs(req.data.decode()),
                             {"veid": ["123"], "api_key": ["private-test"]})
            self.assertIs(build.call_args.args[0], usage.NoRedirect)
            self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 20)

    def test_failures_are_redacted_and_not_pushed(self):
        failures = [b'not-json private-test', b'[]', b'{"error":1,"message":"private-test"}',
                    b'{"error":false}', b'{}', b'{"error":0}']
        for raw in failures:
            with self.subTest(raw=raw), patch.object(usage, "load_credentials", return_value=("123", "private-test")), \
                    patch.object(urllib.request, "build_opener") as build, \
                    patch.object(display_push, "push") as push:
                build.return_value.open.return_value = io.BytesIO(raw)
                with self.assertRaises(SystemExit) as caught:
                    display_push.run(type("Args", (), {"push": "http://localhost", "interval": 0})(), usage.collect)
                self.assertNotIn("private-test", str(caught.exception))
                push.assert_not_called()
        for error in (urllib.error.HTTPError(usage.API_URL, 403, "private-test", {}, None),
                      urllib.error.URLError("private-test"), TimeoutError("private-test")):
            with patch.object(urllib.request, "build_opener") as build:
                build.return_value.open.side_effect = error
                with self.assertRaises(RuntimeError) as caught:
                    usage.fetch_usage("123", "private-test")
                self.assertNotIn("private-test", str(caught.exception))


class DisplayIntegrationTests(unittest.TestCase):
    def test_push_read_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "state.json")
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            httpd.store = server.Store(state)
            httpd.config = {"write_token": "test-write", "read_token": "test-read",
                            "message_token": "test-bot", "stale_after": 900}
            httpd.scheduler = None
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = "http://127.0.0.1:%d" % httpd.server_port
                item = usage.to_display(response(monthly_data_multiplier=0.5))
                with patch.dict(os.environ, {"DISPLAY_WRITE_TOKEN": "test-write"}):
                    display_push.push(base_url, item)
                req = urllib.request.Request(base_url + "/v1/display", headers={"Authorization": "Bearer test-read"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    doc = json.load(resp)
                self.assertEqual(doc["schema_version"], 1)
                sub = doc["subscriptions"][0]
                self.assertEqual(sub["windows"][0]["remaining_bytes"], 375 * GIB)
                self.assertEqual(sub["updated_at"], item["updated_at"])
                self.assertIn("reset_at_utc", sub["windows"][0])
                self.assertEqual(server.Store(state).data["subscriptions"]["banwagong"], item)
            finally:
                httpd.shutdown()
                thread.join(timeout=5)
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
