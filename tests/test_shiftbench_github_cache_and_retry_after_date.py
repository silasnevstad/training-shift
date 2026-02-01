import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
import tempfile
import shutil

from shiftbench.github import GitHubClient


class H(BaseHTTPRequestHandler):
    routes = {}
    calls = {}

    def do_GET(self):
        cnt = H.calls.get(self.path, 0)
        H.calls[self.path] = cnt + 1
        fn = H.routes.get(self.path)
        if fn is None:
            self.send_response(404)
            self.end_headers()
            return
        fn(self, cnt)

    def log_message(self, fmt, *args):
        return


class TestGitHubCacheAndRetryAfterDate(unittest.TestCase):
    def setUp(self):
        H.routes = {}
        H.calls = {}
        self.tmp = tempfile.mkdtemp(prefix="shiftbench_github_cache_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        host, port = self.srv.server_address
        self.base = f"http://{host}:{port}"
        t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))

    def _json(self, handler, status, obj, headers=None):
        body = json.dumps(obj).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        if headers:
            for k, v in headers.items():
                handler.send_header(k, str(v))
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def test_cache_hit_skips_network(self):
        path = "/payload"

        def route(handler, cnt):
            self._json(handler, 200, {"value": 123})

        H.routes[path] = route

        cache_dir = Path(self.tmp) / "cache"
        client = GitHubClient(api_base=self.base, cache_dir=cache_dir, max_attempts=1)

        out1 = client._get_json(self.base + path, cache_key="k")
        out2 = client._get_json(self.base + path, cache_key="k")

        self.assertEqual(out1["data"]["value"], 123)
        self.assertEqual(out2["data"]["value"], 123)
        self.assertEqual(H.calls[path], 1)  # second read came from cache


if __name__ == "__main__":
    unittest.main()
