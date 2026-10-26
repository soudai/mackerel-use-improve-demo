"""Deterministic threaded shipping quote mock for the lock-wait scenario."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlparse(self.path)
        if request.path == "/health":
            self.reply(200, {"status": "ok"})
            return
        if request.path != "/quote":
            self.reply(404, {"error": "not_found"})
            return
        params = parse_qs(request.query)
        try:
            delay_ms = min(5000, max(0, int(params.get("delay_ms", ["300"])[0])))
        except ValueError:
            self.reply(422, {"error": "invalid_delay_ms"})
            return
        time.sleep(delay_ms / 1000)
        self.reply(200, {"shipping_cents": 500, "region": params.get("region", ["tokyo"])[0], "delay_ms": delay_ms})

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
