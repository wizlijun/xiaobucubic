"""Differential tests: native C model against the original Lua source on host only."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT.parents[1] / "apps/xiaobucubic"


class NativeModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temp.name) / "model_probe"
        cjson = ROOT / ".tools/esp-idf/components/json/cJSON"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-I" + str(ROOT / "main"), "-I" + str(cjson),
                        str(ROOT / "main/app_model.c"), str(ROOT / "tests/model_probe.c"),
                        str(cjson / "cJSON.c"), "-lm", "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def probe(self, doc):
        return json.loads(subprocess.check_output([self.binary], input=json.dumps(doc, ensure_ascii=False).encode()))

    def base(self):
        doc = json.loads((APP / "examples/display.json").read_text())
        doc["_now"] = doc["generated_at"]
        return doc

    def test_unknown_percent_limits_and_expiry(self):
        doc = self.base()
        for used, expected in [(None, None), (0, 100), (33.5, 66), (99.6, 0), (125, 0), (-1, None), (1001, None)]:
            doc["subscriptions"][0]["windows"][0]["used_percent"] = used
            self.assertEqual(self.probe(doc)["rows"][0]["windows"][0]["remaining"], expected)
        doc = self.base(); doc["_now"] += 1000
        self.assertEqual(self.probe(doc)["rows"][0]["windows"][0]["state"], "stale")
        doc["messages"] = [{"text": "expires", "expires_at": doc["_now"]}, {"text": "permanent"}]
        self.assertEqual(self.probe(doc)["active"], 1)
        doc["_now"] = None
        self.assertEqual(self.probe(doc)["active"], 1)

    def test_whitespace_and_page_boundaries(self):
        doc = self.base(); doc["messages"] = [{"text": " \t\r\n"}, {"text": "中文" * 100}]
        result = self.probe(doc)
        self.assertEqual(result["messages"], 1)
        self.assertEqual(len(result["bodies"][0]), 180)
        doc["_chunk_text"] = "中" * 180
        self.assertEqual([len(p.replace("\n", "")) for p in self.probe(doc)["chunks"]], [60, 60, 60])
        self.assertTrue(self.probe(doc)["preview"].endswith("…"))

    def test_differential_original_lua(self):
        try:
            from lupa import LuaRuntime
        except ImportError:
            self.skipTest("Run with uv run --with lupa for original-Lua differential coverage")
        lua = LuaRuntime(unpack_returned_tuples=True)
        model = lua.execute((APP / "package/display_model.lua").read_text())

        def convert(value):
            if isinstance(value, dict): return lua.table_from({k: convert(v) for k, v in value.items()})
            if isinstance(value, list): return lua.table_from([convert(v) for v in value])
            return value

        cases = [self.base()]
        for percent in (None, -1, 0, 4.9, 5, 19, 20, 33.5, 95, 99.6, 100, 125, 1001, "34"):
            doc = self.base(); doc["subscriptions"][0]["windows"][0]["used_percent"] = percent; cases.append(doc)
        for condition in ("晴", "晴间多云", "雷阵雨", "雨夹雪", "阴", "雾", "冰雹", "夜晴", "cloud", "snow", "unknown"):
            doc = self.base(); doc["weather"].update(condition=condition, is_day=False); cases.append(doc)
        for clock in (None, 1, self.base()["generated_at"] - 301, self.base()["generated_at"] + 900, self.base()["generated_at"] + 901):
            doc = self.base(); doc["_now"] = clock; cases.append(doc)
        for message in ("", "\n", "\t", "abc\r\ndef\rghi\txyz", "中文" * 100, "a" * 12 + "\n", "\n" * 8, "a\n\n", "x" * 84, "x" * 85):
            doc = self.base(); doc["messages"] = [{"text": message, "expires_at": doc["generated_at"]}]; doc["_chunk_text"] = message; cases.append(doc)
        doc = self.base(); doc["subscriptions"] *= 3; cases.append(doc)
        for count in (0, 1, 2, 3, 4, 5, 6, 7, 12, 13, 30):
            for page in (1, 2, 5):
                doc = self.base(); row = doc["subscriptions"][0]
                doc["subscriptions"] = [dict(row, id=str(i)) for i in range(count)]
                doc["_quota_page"] = page; cases.append(doc)
        for used, total in ((0, 1024), (512, 1024), (1024, 1024), (2048, 1024), (1024**3 + 1, 1024**4), (0.5, 100), (1, 0), (None, 20), (0, 9007199254740991)):
            doc = self.base(); doc["subscriptions"][0]["windows"][0].update(used_bytes=used, total_bytes=total); cases.append(doc)
        for delta in (0, 3600, 86400, 3*86400, 7*86400, 60*86400, -7*86400):
            for offset in (-720, 0, 480, 840):
                doc = self.base(); doc.update(_reset=doc["generated_at"] + delta, _offset=offset); cases.append(doc)
        for message in ("A short English reminder with complete words.", "Read https://example.com/verylongpathbefore/leaving home. 中文提醒。", "word " * 36, "ABCD\n" * 20, "   start  with spaces\tend", "x" * 180):
            doc = self.base(); doc["_chunk_text"] = message; cases.append(doc)
        for doc in cases:
            with self.subTest(index=cases.index(doc)):
                data = model.normalize(convert(doc)); clock = doc.get("_now")
                expected = {"subscriptions": len(data.subscriptions), "messages": len(data.messages), "ttl": data.stale_after_seconds,
                            "secondary": model.has_secondary(data), "weather": model.weather_asset(data.weather), "rows": [],
                            "active": len(model.active_messages(data, clock)), "bodies": [m.text for m in data.messages.values()],
                            "quota_pages": model.quota_pages(data)}
                layout, page = model.subscription_layout(data, doc.get("_quota_page", 1))
                expected["layout"] = [dict(card.items()) for card in layout.values()]
                for s in data.subscriptions.values():
                    expected["rows"].append({"id": s.id, "name": s.name, "windows": [
                        {"label": w.label, "display_label": model.window_label(w), "remaining": model.remaining(w), "state": model.window_state(s, w, clock, data.stale_after_seconds),
                         **({"balance": model.format_bytes(w.remaining_bytes)} if w.remaining_bytes is not None else {})}
                        for w in s.windows.values()]})
                if "_chunk_text" in doc:
                    expected["chunks"] = list(model.message_chunks(doc["_chunk_text"]).values())
                    expected["preview"] = model.message_preview(doc["_chunk_text"])
                if "_reset" in doc: expected["reset_date"] = model.reset_date(doc["_reset"], clock, doc.get("_offset", 480))
                self.assertEqual(self.probe(doc), expected)


if __name__ == "__main__":
    unittest.main()
