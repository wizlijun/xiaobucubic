import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import bandwagon_usage as bandwagon
import display_server


class BandwagonTests(unittest.TestCase):
    def test_display_contract_and_overage(self):
        for used, expected in ((0, 0), (25, 25), (120, 120)):
            with self.subTest(used=used):
                item = bandwagon.to_display({
                    "data_counter": used, "plan_monthly_data": 100,
                    "data_next_reset": "1800000000",
                })
                clean = display_server.clean_subscription("bandwagon", item, 1790000000)
                self.assertEqual(clean["windows"][0]["used_percent"], expected)
                self.assertEqual(clean["windows"][0]["reset_at"], 1800000000)
                if used == 120:
                    self.assertIn("剩余 0.0%", bandwagon.summary(item))

    def test_invalid_usage_never_becomes_fresh_data(self):
        for key, value in (("data_counter", None), ("data_counter", -1),
                           ("data_counter", True), ("data_counter", "NaN"),
                           ("plan_monthly_data", 0), ("plan_monthly_data", "inf"),
                           ("data_next_reset", 1800000000000)):
            with self.subTest(key=key, value=value):
                data = {"data_counter": 25, "plan_monthly_data": 100}
                data[key] = value
                with self.assertRaises(RuntimeError):
                    bandwagon.to_display(data)
        item = bandwagon.to_display({"data_counter": "25", "plan_monthly_data": "100"})
        self.assertIsNone(item["windows"][0]["reset_at"])

    def test_credentials_file_and_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display.env"
            path.write_text("BANDWAGON_VEID=123\nBANDWAGON_API_KEY='file-key'\n")
            with patch.object(bandwagon.display_push, "ENV_FILE", str(path)), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(bandwagon.load_credentials(), ("123", "file-key"))
                with patch.dict(os.environ, {"BANDWAGON_API_KEY": "env-key"}):
                    self.assertEqual(bandwagon.load_credentials(), ("123", "env-key"))
            path.write_text("")
            with patch.object(bandwagon.display_push, "ENV_FILE", str(path)), patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "BANDWAGON_VEID.*BANDWAGON_API_KEY"):
                    bandwagon.load_credentials()

    def test_api_errors_do_not_disclose_credentials(self):
        for error in (urllib.error.URLError("private-secret"),
                      urllib.error.HTTPError("private-secret", 403, "private-secret", {}, None)):
            with patch.object(bandwagon.urllib.request, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(RuntimeError) as caught:
                    bandwagon.fetch_usage("123", "private-secret")
                self.assertNotIn("private-secret", str(caught.exception))

    def test_api_response_validation(self):
        for data in ({"error": 0}, {"error": 1, "message": "private-secret"}, {}, [], {"error": False}):
            with self.subTest(data=data), patch.object(bandwagon.urllib.request, "build_opener") as opener:
                opener.return_value.open.return_value = io.StringIO(json.dumps(data))
                if data == {"error": 0} and type(data["error"]) is int:
                    self.assertEqual(bandwagon.fetch_usage("123", "private-secret"), data)
                else:
                    with self.assertRaises(RuntimeError) as caught:
                        bandwagon.fetch_usage("123", "private-secret")
                    self.assertNotIn("private-secret", str(caught.exception))

    def test_scheduled_collection_pushes_compatible_subscription(self):
        self.assertEqual(display_server.COLLECTORS["bandwagon"], "bandwagon_usage.py")
        with patch.object(bandwagon, "load_credentials", return_value=("123", "secret")), \
                patch.object(bandwagon, "fetch_usage", return_value={"data_counter": 25, "plan_monthly_data": 100}), \
                patch.object(bandwagon.display_push.urllib.request, "urlopen") as post, \
                patch.object(bandwagon.display_push, "write_token", return_value="test-write"):
            post.return_value.__enter__.return_value.read.return_value = b'{}'
            item = bandwagon.collect()
            bandwagon.display_push.push("http://127.0.0.1:8007", item)
            request = post.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8007/v1/subscriptions/bandwagon")
            self.assertEqual(request.method, "PUT")
            saved = display_server.clean_subscription("bandwagon", json.loads(request.data), 1790000000)
            state = {"subscriptions": {"bandwagon": saved}, "weather": None, "messages": []}
            response = json.loads(display_server.build_display(state, 900, 1790000000))
            self.assertEqual(response["subscriptions"][0]["windows"][0]["used_percent"], 25)


if __name__ == "__main__":
    unittest.main()
