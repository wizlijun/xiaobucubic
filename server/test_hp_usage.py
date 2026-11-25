import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import display_push
import display_server
import energy_usage
import hp_model
import hp_usage
import oura_auth
import oura_client


_log_patch = patch.object(hp_usage, "log")


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


class QuietHandler(display_server.Handler):
    def log_message(self, *args):
        pass


def result(level=55, status="尚可", trend="draining", note="生理压力高"):
    return hp_model.Result(level=level, status=status, trend=trend, note=note, state="day",
                           steps=[], anchor_day=None, readiness=None, profile=None)


def hp_hp_item():
    return hp_usage.build_item(result(), 5)


def args(**kw):
    base = dict(age=None, params=None, now=None, push=None, follow=False, json=False,
                explain=False, report=False, days=28)
    base.update(kw)
    return SimpleNamespace(**base)


class ItemTests(unittest.TestCase):
    def test_build_item(self):
        item = hp_usage.build_item(result(), 1795581200)
        self.assertEqual(item["name"], "HP")
        self.assertEqual(item["level_percent"], 55)
        self.assertEqual(item["status"], "尚可")
        self.assertEqual(item["trend"], "draining")
        self.assertEqual(item["note"], "生理压力高")
        self.assertEqual(item["source"], "estimated")
        self.assertEqual(item["stale_after_seconds"], 1800)
        self.assertEqual(item["updated_at"], 1795581200)

    def test_null_item(self):
        item = hp_usage.build_item(result(level=None, status="待同步", trend=None, note=None), 1795581200)
        self.assertIsNone(item["level_percent"])
        self.assertNotIn("trend", item)

    def test_auth_item(self):
        item = hp_usage.auth_item(1795581200)
        self.assertIsNone(item["level_percent"])
        self.assertEqual(item["status"], "待授权")


class CycleTests(unittest.TestCase):
    NOW = 1795581200

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(hp_usage, "CACHE_FILE", self.temp.name + "/hp_cache.json"),
                        patch.object(hp_usage, "_PERSONAL_INFO", None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_auth_required_pushes_auth_item(self):
        with patch.object(oura_client, "fetch_all", side_effect=oura_auth.AuthRequired("x")):
            item = hp_usage.cycle(args(), self.NOW)
        self.assertEqual(item["status"], "待授权")

    def test_auth_required_in_baseline(self):
        with patch.object(oura_client, "fetch_all", return_value={}), \
             patch.object(oura_client, "personal_info", return_value={"age": 30}), \
             patch.object(oura_client, "fetch_baseline_hr", side_effect=oura_auth.AuthRequired("x")):
            item = hp_usage.cycle(args(), self.NOW)
        self.assertEqual(item["status"], "待授权")

    def test_rate_limited_skips(self):
        with patch.object(oura_client, "fetch_all", side_effect=oura_client.RateLimited(60)):
            self.assertIsNone(hp_usage.cycle(args(), self.NOW))

    def test_other_errors_skip(self):
        for exc in (RuntimeError("boom"), OSError("net")):
            with patch.object(oura_client, "fetch_all", side_effect=exc):
                self.assertIsNone(hp_usage.cycle(args(), self.NOW))

    def test_happy_path_personal_info_once(self):
        rows = [{"timestamp": "2026-11-20T10:00:00+08:00", "bpm": 60, "source": "awake"}]
        with patch.object(oura_client, "fetch_all", return_value={"sleep": []}) as fa, \
             patch.object(oura_client, "personal_info", return_value={"age": 41}) as pi, \
             patch.object(oura_client, "fetch_baseline_hr", return_value=rows) as fb, \
             patch.object(hp_model, "compute", return_value=result()) as comp:
            item = hp_usage.cycle(args(age=33), self.NOW)
            hp_usage.cycle(args(age=33), self.NOW + 600)
        self.assertEqual(item["level_percent"], 55)
        self.assertEqual(pi.call_count, 1)
        self.assertEqual(fb.call_count, 1)
        self.assertEqual(fa.call_count, 2)
        call = comp.call_args
        self.assertEqual(call.args[1]["personal_info"], {"age": 41})
        self.assertEqual(call.args[2], 60.0)
        self.assertEqual(call.kwargs["age"], 33)

    def test_personal_info_error_proceeds(self):
        with patch.object(oura_client, "fetch_all", return_value={}), \
             patch.object(oura_client, "personal_info", side_effect=RuntimeError("x")), \
             patch.object(oura_client, "fetch_baseline_hr", return_value=[]), \
             patch.object(hp_model, "compute", return_value=result()) as comp:
            item = hp_usage.cycle(args(age=30), self.NOW)
        self.assertIsNotNone(item)
        self.assertNotIn("personal_info", comp.call_args.args[1])
        self.assertEqual(comp.call_args.kwargs["age"], 30)

    def test_personal_info_auth_required(self):
        with patch.object(oura_client, "fetch_all", return_value={}), \
             patch.object(oura_client, "personal_info", side_effect=oura_auth.AuthRequired("x")):
            item = hp_usage.cycle(args(), self.NOW)
        self.assertEqual(item["status"], "待授权")


class CacheTests(unittest.TestCase):
    def test_cache_daily(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/c.json"
            calls = []

            def fetch(day):
                calls.append(day)
                return 61.5, 20
            self.assertEqual(hp_usage.cached_hr_quiet(date(2026, 11, 25), fetch, path), 61.5)
            self.assertEqual(hp_usage.cached_hr_quiet(date(2026, 11, 25), fetch, path), 61.5)
            self.assertEqual(len(calls), 1)
            hp_usage.cached_hr_quiet(date(2026, 11, 26), fetch, path)
            self.assertEqual(len(calls), 2)
            with open(path) as f:
                self.assertEqual(json.load(f), {"day": "2026-11-26", "hr_quiet": 61.5, "valid_days": 20})
            self.assertEqual(os.listdir(d), ["c.json"])

    def test_corrupt_cache_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/c.json"
            with open(path, "w") as f:
                f.write("{nope")
            self.assertEqual(hp_usage.cached_hr_quiet(date(2026, 11, 25), lambda day: (50.0, 3), path), 50.0)


class BaselineRetryTests(unittest.TestCase):
    def test_none_baseline_not_cached(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/c.json"
            results = [(None, 0), (58.0, 12)]
            calls = []

            def fetch(day):
                calls.append(day)
                return results.pop(0)
            day = date(2026, 11, 25)
            self.assertIsNone(hp_usage.cached_hr_quiet(day, fetch, path))
            self.assertFalse(os.path.exists(path))
            self.assertEqual(hp_usage.cached_hr_quiet(day, fetch, path), 58.0)
            self.assertEqual(hp_usage.cached_hr_quiet(day, fetch, path), 58.0)
            self.assertEqual(len(calls), 2)


class RealAuthChainTests(unittest.TestCase):
    def run_cycle(self, content):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/oura_token.json"
            if content is not None:
                with open(path, "w") as f:
                    f.write(content)
            defaults = (path, None, None, False)
            with patch.object(oura_auth.access_token, "__defaults__", defaults), \
                 patch.object(hp_usage, "CACHE_FILE", d + "/hp_cache.json"), \
                 patch.object(hp_usage, "_PERSONAL_INFO", None), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("network reached")):
                return hp_usage.cycle(args(), 1795581200)

    def test_missing_token_file(self):
        item = self.run_cycle(None)
        self.assertEqual(item["status"], "待授权")
        self.assertIsNone(item["level_percent"])

    def test_corrupt_token_file(self):
        item = self.run_cycle("{bad")
        self.assertEqual(item["status"], "待授权")
        self.assertIsNone(item["level_percent"])


class FollowTests(unittest.TestCase):
    def test_follow_survives_push_error(self):
        pushed = []

        def push_fn(item):
            pushed.append(item)
            if len(pushed) == 1:
                raise OSError("down")
        cycles = []
        sleeps = []
        hp_usage.follow(args(), lambda now: cycles.append(now) or {"n": len(cycles)}, push_fn,
                        sleep=sleeps.append, clock=lambda: 1000, max_cycles=2)
        self.assertEqual(len(cycles), 2)
        self.assertEqual(len(pushed), 2)
        self.assertEqual(sleeps, [200])

    def test_follow_survives_cycle_error_and_skips_none(self):
        outcomes = [RuntimeError("x"), None, {"a": 1}]
        pushed = []

        def cycle_fn(now):
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return o
        hp_usage.follow(args(), cycle_fn, pushed.append, sleep=lambda s: None, clock=lambda: 5, max_cycles=3)
        self.assertEqual(pushed, [{"a": 1}])

    def test_follow_aligns_to_600(self):
        sleeps = []
        hp_usage.follow(args(), lambda n: None, lambda i: None, sleep=sleeps.append,
                        clock=lambda: 1000, max_cycles=2)
        self.assertEqual(sleeps, [200])
        sleeps.clear()
        hp_usage.follow(args(), lambda n: None, lambda i: None, sleep=sleeps.append,
                        clock=lambda: 1200, max_cycles=2)
        self.assertEqual(sleeps, [600])

    def test_keyboard_interrupt_propagates(self):
        def boom(now):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            hp_usage.follow(args(), boom, lambda i: None, sleep=lambda s: None, clock=lambda: 1, max_cycles=2)


class CliTests(unittest.TestCase):
    def test_report_stub(self):
        with self.assertRaises(SystemExit) as cm:
            hp_usage.main(["--report"])
        self.assertIn("not implemented", str(cm.exception))

    def test_unknown_param_exits(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/p.json"
            with open(path, "w") as f:
                json.dump({"bogus": 1}, f)
            with self.assertRaises(SystemExit) as cm:
                hp_usage.main(["--params", path])
            self.assertIn("bogus", str(cm.exception))

    def test_params_loaded_once_in_main_and_passed_down(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/p.json"
            with open(path, "w") as f:
                json.dump({}, f)
            with patch.object(hp_usage, "cycle", return_value=hp_hp_item()) as cy, \
                 patch("builtins.print"):
                hp_usage.main(["--params", path, "--json"])
            self.assertEqual(cy.call_args.args[2], hp_model.make_params())

    def test_params_not_reread_in_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(hp_usage, "load_params", side_effect=SystemExit("no")), \
                 patch.object(hp_usage, "CACHE_FILE", d + "/c.json"), \
                 patch.object(hp_usage, "_PERSONAL_INFO", None), \
                 patch.object(oura_client, "fetch_all", return_value={}), \
                 patch.object(oura_client, "personal_info", return_value={}), \
                 patch.object(oura_client, "fetch_baseline_hr", return_value=[]), \
                 patch.object(hp_model, "compute", return_value=result()):
                self.assertIsNotNone(hp_usage.cycle(args(), 1795581200))

    def test_push_wiring(self):
        item = hp_hp_item()
        with patch.object(hp_usage, "cycle", return_value=item), \
             patch.object(display_push, "push") as push, patch("builtins.print"):
            hp_usage.main(["--push", "http://x:1"])
        push.assert_called_once_with("http://x:1", item, path="/v1/energy")

    def test_push_follow_reaches_follow(self):
        with patch.object(hp_usage, "follow") as fol, \
             patch.object(display_push, "push") as push, \
             patch.object(hp_usage, "cycle", return_value=hp_hp_item()):
            hp_usage.main(["--push", "http://x:1", "--follow"])
            self.assertEqual(fol.call_count, 1)
            fol.call_args.args[2](hp_hp_item())  # push_fn
        self.assertEqual(push.call_args.kwargs["path"], "/v1/energy")
        self.assertEqual(push.call_args.args[0], "http://x:1")

    def test_now_parsed_and_json_output(self):
        out = []
        with patch.object(hp_usage, "cycle", return_value=hp_usage.build_item(result(), 5)) as cy, \
             patch("builtins.print", side_effect=lambda *a, **k: out.append(a[0])):
            hp_usage.main(["--now", "2026-11-25T10:00:00+08:00", "--json"])
        self.assertEqual(cy.call_args.args[1], hp_model.parse_ts("2026-11-25T10:00:00+08:00"))
        self.assertEqual(json.loads(out[0])["level_percent"], 55)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = display_server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.server.daemon_threads = True
        self.server.store = display_server.Store(self.temp.name + "/state.json")
        self.server.config = {"read_token": "reader", "write_token": "writer", "message_token": "bot", "stale_after": 900}
        self.server.scheduler = None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        self.token = patch.object(display_push, "write_token", return_value="writer")
        self.token.start()

    def tearDown(self):
        self.token.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_end_to_end_display(self):
        now = int(datetime.now(timezone.utc).timestamp())
        display_push.push(self.url, hp_usage.build_item(result(), now), path="/v1/energy")
        req = urllib.request.Request(self.url + "/v1/display", headers={"Authorization": "Bearer reader"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            doc = json.load(resp)
        sub = doc["subscriptions"][0]
        self.assertEqual(sub["id"], "energy")
        self.assertEqual(sub["windows"][0]["label"], "尚可 · 生理压力高")
        self.assertEqual(sub["windows"][0]["used_percent"], 45)


if __name__ == "__main__":
    unittest.main()
