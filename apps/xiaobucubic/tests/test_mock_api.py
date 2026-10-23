import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("mock_api",ROOT/"tools/mock_api.py")
mock=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock)


class MockTest(unittest.TestCase):
    def test_auth_and_fixture_timestamps(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),mock.handler(ROOT/"examples/display.json","test-token"))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url=f"http://127.0.0.1:{server.server_port}/v1/display"
        try:
            with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(url)
            self.assertEqual(err.exception.code,401)
            err.exception.close()
            request=urllib.request.Request(url,headers={"Authorization":"Bearer test-token"})
            with urllib.request.urlopen(request) as response: doc=json.load(response)
            self.assertTrue(doc["demo"])
            self.assertEqual(doc["generated_at"]-doc["subscriptions"][0]["updated_at"],60)
            self.assertEqual(doc["subscriptions"][0]["windows"][0]["reset_at"]-doc["generated_at"],7200)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=="__main__":unittest.main()
