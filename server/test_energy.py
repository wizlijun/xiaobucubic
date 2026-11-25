import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import display_push
import display_server
import energy_usage


class QuietHandler(display_server.Handler):
    def log_message(self, *args):
        pass


class EnergyValidationTests(unittest.TestCase):
    def test_clean_energy_defaults_and_optional_fields(self):
        now = 1795581200
        minimal = display_server.clean_energy({}, now)
        self.assertEqual(minimal, {
            "name": "HP",
            "level_percent": None,
            "source": "unknown",
            "updated_at": now,
        })
        full = display_server.clean_energy({
            "name": "精力",
            "level_percent": 78.46,
            "status": "充沛",
            "trend": "charging",
            "note": "睡眠 7.5h · HRV 62",
            "source": "manual",
            "updated_at": now - 10,
            "stale_after_seconds": 14400,
        }, now)
        self.assertEqual(full, {
            "name": "精力",
            "level_percent": 78.5,
            "status": "充沛",
            "trend": "charging",
            "note": "睡眠 7.5h · HRV 62",
            "source": "manual",
            "updated_at": now - 10,
            "stale_after_seconds": 14400,
        })

    def test_clean_energy_rejects_invalid_values(self):
        now = 1795581200
        for bad in (
            "not-an-object",
            {"source": "invalid"},
            {"trend": "up"},
            {"trend": 123},
            {"level_percent": "high"},
            {"level_percent": True},
            {"stale_after_seconds": 30},
            {"stale_after_seconds": 7 * 86400 + 1},
            {"stale_after_seconds": True},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(display_server.BadRequest):
                    display_server.clean_energy(bad, now)

    def test_energy_usage_build_payload(self):
        item = energy_usage.build_payload(
            level=82.0, status="充沛", trend="steady", note="睡眠 8h",
            source="manual", stale_after=7200, updated_at=1795581200,
        )
        self.assertEqual(item["level_percent"], 82)
        self.assertEqual(display_server.clean_energy(item, 1795581200), item)
        with self.assertRaises(RuntimeError):
            energy_usage.build_payload(level=105)
        with self.assertRaises(RuntimeError):
            energy_usage.build_payload(level=-1)


class EnergyProtocolTests(unittest.TestCase):
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

    def get_display(self):
        req = urllib.request.Request(self.url + "/v1/display", headers={"Authorization": "Bearer reader"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.load(resp)

    def test_put_read_and_delete_energy(self):
        self.assertIsNone(self.get_display()["energy"])

        for bad_token in ("reader", "bot", ""):
            with patch.object(display_push, "write_token", return_value=bad_token):
                with self.assertRaises(RuntimeError):
                    display_push.request_json(self.url, "/v1/energy", {"level_percent": 50}, method="PUT")

        item = energy_usage.build_payload(
            level=76, status="充沛", trend="charging", note="午休后",
            source="manual", stale_after=14400, updated_at=1795581200,
        )
        reply = display_push.push(self.url, item, path="/v1/energy")
        self.assertEqual(reply["energy"]["level_percent"], 76)
        self.assertIn("updated_at_utc", reply["energy"])

        doc = self.get_display()
        self.assertEqual(doc["energy"]["name"], "HP")
        self.assertEqual(doc["energy"]["level_percent"], 76)
        self.assertEqual(doc["energy"]["status"], "充沛")
        self.assertEqual(doc["energy"]["trend"], "charging")
        self.assertEqual(doc["energy"]["note"], "午休后")
        self.assertEqual(doc["energy"]["stale_after_seconds"], 14400)
        self.assertIn("updated_at_utc", doc["energy"])
        # 同步投影到 subscriptions 首位，旧客户端无需升级即可动态展示。
        self.assertEqual(len(doc["subscriptions"]), 1)
        sub = doc["subscriptions"][0]
        self.assertEqual(sub["id"], "energy")
        self.assertEqual(sub["name"], "HP")
        self.assertEqual(sub["windows"][0]["label"], "充沛 · 午休后")
        self.assertEqual(sub["windows"][0]["used_percent"], 24)

        reloaded = display_server.Store(self.temp.name + "/state.json").data
        self.assertEqual(reloaded["energy"]["level_percent"], 76)
        self.assertNotIn("energy", reloaded["subscriptions"])

        deleted = display_push.request_json(self.url, "/v1/energy", None, method="DELETE")
        self.assertIsNone(deleted["energy"])
        after = self.get_display()
        self.assertIsNone(after["energy"])
        self.assertEqual(after["subscriptions"], [])

    def test_energy_independent_ttl_and_ordering_before_subscriptions(self):
        now = 1795585000
        data = {
            "subscriptions": {
                "claude": {"id": "claude", "name": "Claude", "source": "official", "updated_at": now, "windows": []},
            },
            "energy": {
                "name": "能量", "level_percent": 78, "source": "manual",
                "updated_at": now - 3600, "status": "充沛", "note": "示例数据",
                "stale_after_seconds": 14400,
            },
            "messages": [],
            "weather": None,
        }
        doc = json.loads(display_server.build_display(data, 900, now).decode("utf-8"))
        self.assertEqual([s["id"] for s in doc["subscriptions"]], ["energy", "claude"])
        self.assertEqual(doc["subscriptions"][0]["updated_at"], now)
        self.assertEqual(doc["subscriptions"][0]["windows"][0]["used_percent"], 22)
        self.assertEqual(doc["subscriptions"][0]["windows"][0]["label"], "充沛 · 示例数据")

        expired_doc = json.loads(display_server.build_display(data, 900, now + 20000).decode("utf-8"))
        self.assertEqual(expired_doc["subscriptions"][0]["updated_at"], now - 3600)


if __name__ == "__main__":
    unittest.main()
