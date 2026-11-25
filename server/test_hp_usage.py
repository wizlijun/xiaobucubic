import json
import os
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import display_push
import display_server
import energy_usage
import hp_model
import hp_usage
import oura_auth
import oura_client
import test_hp_model


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


class BaselineFailureTests(unittest.TestCase):
    def test_fetch_error_returns_stale_cache(self):
        with tempfile.TemporaryDirectory() as d:
            path = d + "/c.json"
            hp_usage._write_cache(path, {"day": "2026-11-24", "hr_quiet": 57.0, "valid_days": 20})
            with open(path) as f:
                before = f.read()

            def fetch(day):
                raise RuntimeError("boom")
            logged = []
            with patch.object(hp_usage, "log", side_effect=logged.append):
                self.assertEqual(hp_usage.cached_hr_quiet(date(2026, 11, 25), fetch, path), 57.0)
            self.assertEqual(len(logged), 1)
            with open(path) as f:
                self.assertEqual(f.read(), before)

    def test_fetch_error_without_cache_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            def fetch(day):
                raise OSError("down")
            self.assertIsNone(hp_usage.cached_hr_quiet(date(2026, 11, 25), fetch, d + "/c.json"))
            self.assertEqual(os.listdir(d), [])

    def test_auth_required_still_propagates(self):
        def fetch(day):
            raise oura_auth.AuthRequired("x")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(oura_auth.AuthRequired):
                hp_usage.cached_hr_quiet(date(2026, 11, 25), fetch, d + "/c.json")


class ReportWindowTests(unittest.TestCase):
    def test_sleep_and_readiness_start_early(self):
        calls = {}

        def get(name, *a, **kw):
            calls[name] = kw
            return []
        today = date(2026, 11, 27)
        tz = timezone(timedelta(hours=8))
        with patch.object(oura_client, "get", side_effect=get), \
             patch.object(oura_client, "personal_info", return_value={}):
            hp_usage._report_data(hp_model.parse_ts("2026-11-27T10:00:00+08:00"), tz, today, 2)
        self.assertEqual(calls["sleep"]["start_date"], "2026-10-27")
        self.assertEqual(calls["daily_readiness"]["start_date"], "2026-10-27")
        self.assertEqual(calls["daily_activity"]["start_date"], "2026-11-24")
        self.assertEqual(calls["workout"]["start_date"], "2026-11-24")
        self.assertEqual(calls["sleep"]["end_date"], "2026-11-28")


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


class CollectTests(unittest.TestCase):
    def test_collect_returns_item(self):
        item = hp_hp_item()
        with patch.object(hp_usage, "cycle", return_value=item) as cy:
            self.assertEqual(hp_usage.collect(args(), {"x": 1}, clock=lambda: 1234.5), item)
        self.assertEqual(cy.call_args.args[1:], (1234, {"x": 1}))

    def test_collect_none_raises_runtime_error(self):
        with patch.object(hp_usage, "cycle", return_value=None):
            with self.assertRaises(RuntimeError):
                hp_usage.collect(args(), None)

    def test_collect_wraps_unexpected_error_with_type(self):
        with patch.object(hp_usage, "cycle", side_effect=KeyError("k")):
            with self.assertRaisesRegex(RuntimeError, "KeyError"):
                hp_usage.collect(args(), None)

    def test_keyboard_interrupt_propagates(self):
        with patch.object(hp_usage, "cycle", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                hp_usage.collect(args(), None)


class SchedulerIntegrationTests(unittest.TestCase):
    def test_energy_collector_is_hp_usage(self):
        self.assertEqual(display_server.COLLECTORS["energy"], "hp_usage.py")

    def test_energy_lease_outlives_daily_baseline_fetch(self):
        now = [0]
        scheduler = display_server.Scheduler(clock=lambda: now[0], wall_clock=lambda: 1800000000)
        scheduler.on_request()
        lease = scheduler.poll("energy")["lease_id"]
        self.assertIsNotNone(lease)
        now[0] = 240  # 每日首轮拉 28 天基线约 2.5 分钟
        scheduler.submit("energy", lease, lambda: None)
        self.assertGreater(display_server.COLLECT_TIMEOUTS["energy"], 240)


class ReportTests(unittest.TestCase):
    TZ = timezone(timedelta(hours=8))
    NOW = hp_model.parse_ts("2026-11-27T10:00:00+08:00")

    def data(self):
        d = test_hp_model.example_day_data()
        d["sleep"] = d["sleep"] + [test_hp_model.sleep("2026-11-26", "2026-11-25T23:00:00+08:00",
                                                       "2026-11-26T07:00:00+08:00", 8 * 3600)]
        return d

    def run_report(self, stress_rows, a=None, now=None, **over):
        d = self.data()
        rows = {"sleep": d["sleep"], "daily_readiness": d["daily_readiness"],
                "daily_activity": d["daily_activity"], "workout": [], "heartrate": d["heartrate"]}
        get = lambda name, *a_, **kw: rows[name]
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            server_dir = os.path.dirname(hp_usage.__file__)
            before = sorted(os.listdir(server_dir))
            try:
                with patch.object(hp_usage, "CACHE_FILE", tmp + "/hp_cache.json"), \
                     patch.object(hp_usage, "local_tz", return_value=self.TZ), \
                     patch.object(oura_client, "get", side_effect=get), \
                     patch.object(oura_client, "personal_info", return_value=d["personal_info"]), \
                     patch.object(oura_client, "fetch_baseline_hr", return_value=[]), \
                     patch.object(oura_client, "fetch_stress", return_value=stress_rows), \
                     patch.object(hp_model, "quiet_hr", return_value=62):
                    out = hp_usage.report(a or args(days=2), now or self.NOW, **over)
            finally:
                os.chdir(cwd)
            self.assertEqual(os.listdir(tmp), [])
            self.assertEqual(sorted(os.listdir(server_dir)), before)
        return out

    def test_report_lines(self):
        out = self.run_report([{"day": "2026-11-25", "stress_high": 600, "recovery_high": 40},
                               {"day": "2026-11-26", "stress_high": 700, "recovery_high": 50}])
        lines = out.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("2026-11-25 anchor=88(readiness) bed_hp=19"))
        self.assertIn("stress=630/600 recovery=30/40", lines[0])
        self.assertIn("zero=0% full=0%", lines[0])
        self.assertTrue(lines[1].startswith("2026-11-26 "))
        self.assertIn("stress_high 单位: 分钟", lines[2])
        self.assertIn("stress 模型 ", lines[2])
        self.assertIn("vs stress_high 650 ", lines[2])
        self.assertIn("exp_load=", lines[2])

    def test_report_seconds_converted(self):
        out = self.run_report([{"day": "2026-11-25", "stress_high": 36000, "recovery_high": 1800}])
        line = out.split("\n")[0]
        self.assertIn("stress=630/600 recovery=30/30", line)
        self.assertIn("stress_high 单位: 秒", out)

    def test_report_without_stress_rows(self):
        out = self.run_report([])
        self.assertIn("stress=630/-- recovery=30/--", out)
        self.assertIn("单位: 无数据", out)

    def test_report_skips_days_without_main_sleep(self):
        out = self.run_report([], a=args(days=2), now=hp_model.parse_ts("2026-11-28T10:00:00+08:00"))
        lines = out.split("\n")
        self.assertEqual(len(lines), 2)  # 11-26 reported, 11-27 skipped
        self.assertTrue(lines[0].startswith("2026-11-26 "))
        self.assertTrue(lines[1].startswith("汇总 1 天"))

    def test_report_error_is_one_line_exit(self):
        for exc, text in ((oura_auth.AuthRequired(), "未授权"), (oura_client.RateLimited(30), "限流"),
                          (RuntimeError("boom"), "boom")):
            with patch.object(hp_usage, "local_tz", return_value=self.TZ), \
                 patch.object(oura_client, "get", side_effect=exc):
                with self.assertRaises(SystemExit) as cm:
                    hp_usage.report(args(days=2), self.NOW)
            self.assertIn(text, str(cm.exception))
            self.assertNotIn("\n", str(cm.exception))


class CliTests(unittest.TestCase):
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

    def test_push_follow_uses_scheduled_run(self):
        item = hp_hp_item()
        with patch.object(display_push, "run") as run, \
             patch.object(hp_usage, "cycle", return_value=item):
            hp_usage.main(["--push", "http://x:1", "--follow"])
            self.assertEqual(run.call_count, 1)
            a = run.call_args
            self.assertEqual(a.args[0].push, "http://x:1")
            self.assertEqual(a.args[0].collector, "energy")
            self.assertEqual(a.kwargs["path"], "/v1/energy")
            self.assertEqual(a.args[1](), item)  # collect

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
