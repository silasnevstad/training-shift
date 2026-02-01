import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from shiftbench.github import GitHubClient
from shiftbench.errors import SBError, E_HTTP_403


class GHHandler(BaseHTTPRequestHandler):
    routes = {}
    calls = {}
    last_headers = {}

    def do_GET(self):
        # Capture raw headers (original casing may vary; treat as case-insensitive in tests)
        GHHandler.last_headers[self.path] = dict(self.headers)
        cnt = GHHandler.calls.get(self.path, 0)
        GHHandler.calls[self.path] = cnt + 1

        fn = GHHandler.routes.get(self.path)
        if fn is None:
            self.send_response(404)
            self.end_headers()
            return
        fn(self, cnt)

    def log_message(self, fmt, *args):
        return


class TestGitHubRateLimit(unittest.TestCase):
    def setUp(self):
        GHHandler.routes = {}
        GHHandler.calls = {}
        GHHandler.last_headers = {}

        self.srv = HTTPServer(("127.0.0.1", 0), GHHandler)
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

    def _hdr_ci(self, path: str):
        """Case-insensitive view of captured request headers."""
        raw = GHHandler.last_headers.get(path) or {}
        return {str(k).lower(): str(v) for k, v in raw.items()}

    def test_sends_api_version_header(self):
        path = "/ok"

        def route(handler, cnt):
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=1)

        out = client._get_json(self.base + path)
        self.assertTrue(out["data"]["ok"])

        hdrs = self._hdr_ci(path)
        got = hdrs.get("x-github-api-version")
        if got != "2022-11-28":
            # Helpful failure output for diagnosis
            self.fail(
                f"missing/incorrect X-GitHub-Api-Version; got={got!r}; captured_headers={GHHandler.last_headers.get(path)!r}"
            )

    def test_429_retry_after_retries(self):
        path = "/rate429"

        def route(handler, cnt):
            if cnt == 0:
                self._json(handler, 429, {"message": "rate limit exceeded"}, headers={"Retry-After": "2"})
                return
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=2)

        sleep_calls = []
        with mock.patch("shiftbench.github.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            out = client._get_json(self.base + path)

        self.assertEqual(out["data"]["ok"], True)
        self.assertEqual(GHHandler.calls[path], 2)
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(int(sleep_calls[0]), 2)

    def test_403_primary_rate_limit_remaining_zero_waits_until_reset(self):
        path = "/rate403_primary"
        reset_epoch = 1010  # time.time mocked to 1000 => wait is 11 (includes +1 buffer)

        def route(handler, cnt):
            if cnt == 0:
                self._json(
                    handler,
                    403,
                    {"message": "API rate limit exceeded"},
                    headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_epoch)},
                )
                return
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=2)

        sleep_calls = []
        with mock.patch("shiftbench.github.time.time", return_value=1000), mock.patch(
            "shiftbench.github.time.sleep", side_effect=lambda s: sleep_calls.append(s)
        ):
            out = client._get_json(self.base + path)

        self.assertEqual(out["data"]["ok"], True)
        self.assertEqual(GHHandler.calls[path], 2)
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(int(sleep_calls[0]), 11)

    def test_403_secondary_rate_limit_retry_after(self):
        path = "/rate403_secondary"

        def route(handler, cnt):
            if cnt == 0:
                self._json(
                    handler,
                    403,
                    {"message": "You have exceeded a secondary rate limit"},
                    headers={"Retry-After": "1"},
                )
                return
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=2)

        sleep_calls = []
        with mock.patch("shiftbench.github.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            out = client._get_json(self.base + path)

        self.assertEqual(out["data"]["ok"], True)
        self.assertEqual(GHHandler.calls[path], 2)
        self.assertEqual(int(sleep_calls[0]), 1)

    def test_403_not_rate_limited_fails_without_retry(self):
        path = "/forbidden"

        def route(handler, cnt):
            self._json(handler, 403, {"message": "forbidden"}, headers={"X-RateLimit-Remaining": "10"})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=3)

        with mock.patch("shiftbench.github.time.sleep") as sleep:
            with self.assertRaises(SBError) as ctx:
                client._get_json(self.base + path)

        self.assertEqual(ctx.exception.code, E_HTTP_403)
        self.assertEqual(GHHandler.calls[path], 1)
        sleep.assert_not_called()

    def test_secondary_rate_limit_without_retry_after_waits_at_least_60s(self):
        path = "/rate403_secondary_no_retry_after"

        def route(handler, cnt):
            if cnt == 0:
                self._json(
                    handler,
                    403,
                    {"message": "You have exceeded a secondary rate limit"},
                    headers={"X-RateLimit-Remaining": "10"},
                )
                return
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=2)

        sleep_calls = []
        with mock.patch("shiftbench.github.time.sleep", side_effect=lambda s: sleep_calls.append(s)), mock.patch(
            "shiftbench.github.random.uniform", return_value=0.0
        ):
            out = client._get_json(self.base + path)

        self.assertTrue(out["data"]["ok"])
        self.assertEqual(GHHandler.calls[path], 2)
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreaterEqual(float(sleep_calls[0]), 60.0)

    def test_primary_rate_limit_remaining_zero_without_reset_falls_back_to_min_wait(self):
        path = "/rate403_primary_no_reset"

        def route(handler, cnt):
            if cnt == 0:
                self._json(
                    handler,
                    403,
                    {"message": "API rate limit exceeded"},
                    headers={"X-RateLimit-Remaining": "0"},
                )
                return
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=2)

        sleep_calls = []
        with mock.patch("shiftbench.github.time.sleep", side_effect=lambda s: sleep_calls.append(s)), mock.patch(
            "shiftbench.github.random.uniform", return_value=0.0
        ):
            out = client._get_json(self.base + path)

        self.assertTrue(out["data"]["ok"])
        self.assertEqual(GHHandler.calls[path], 2)
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreaterEqual(float(sleep_calls[0]), 60.0)

    def test_non_rate_limit_403_with_retry_after_is_treated_rate_limited(self):
        path = "/forbidden_retry_after"

        def route(handler, cnt):
            if cnt == 0:
                # Not a secondary-rate-limit message and remaining is nonzero, but Retry-After should force rate-limit handling.
                self._json(
                    handler,
                    403,
                    {"message": "forbidden"},
                    headers={"X-RateLimit-Remaining": "10", "Retry-After": "2"},
                )
                return
            self._json(handler, 200, {"ok": True})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=2)

        sleep_calls = []
        with mock.patch("shiftbench.github.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            out = client._get_json(self.base + path)

        self.assertTrue(out["data"]["ok"])
        self.assertEqual(GHHandler.calls[path], 2)
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(int(sleep_calls[0]), 2)

    def test_404_private_resource_unauthenticated_is_not_retried(self):
        path = "/private_404"

        def route(handler, cnt):
            self._json(handler, 404, {"message": "Not Found"})

        GHHandler.routes[path] = route
        client = GitHubClient(api_base=self.base, cache_dir=None, max_attempts=5)

        with mock.patch("shiftbench.github.time.sleep") as sleep:
            with self.assertRaises(SBError) as ctx:
                client._get_json(self.base + path)

        # Must fail fast on 404: no retry masking.
        self.assertEqual(ctx.exception.code, "E_REF_NOT_FOUND")
        self.assertEqual(GHHandler.calls[path], 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
