#!/usr/bin/env python3
"""Development fixture only: no subscription scraping or weather collection."""
import argparse
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def fresh_fixture(path):
    doc = json.loads(path.read_text())
    delta = int(time.time()) - doc["generated_at"]
    def shift(obj):
        if isinstance(obj, dict):
            return {k: v + delta if k in ("generated_at", "updated_at", "reset_at", "due_at")
                    and type(v) in (int, float) else shift(v) for k, v in obj.items()}
        if isinstance(obj, list): return [shift(v) for v in obj]
        return obj
    doc = shift(doc)
    doc["demo"] = True  # This server can never pretend to provide live account data.
    return doc


def handler(fixture, token):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/v1/display":
                self.send_error(404)
                return
            provided = self.headers.get("Authorization", "")
            if token and not hmac.compare_digest(provided, "Bearer " + token):
                self.send_error(401)
                return
            try:
                body = json.dumps(fresh_fixture(fixture), ensure_ascii=False).encode()
            except (OSError, ValueError, KeyError):
                self.send_error(503, "Fixture unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Do not log authorization headers.
            print("mock-api", fmt % args, flush=True)
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[1]/"examples/display.json")
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    token = args.token_file.read_text().strip() if args.token_file else ""
    server = ThreadingHTTPServer((args.host, args.port), handler(args.fixture, token))
    print(f"DEMO ONLY: http://{args.host}:{args.port}/v1/display", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
