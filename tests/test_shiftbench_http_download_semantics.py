import threading
import tempfile
import shutil
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from shiftbench.errors import SBError, E_TRUNCATED_DOWNLOAD, E_HTTP_429
from shiftbench.http import stream_download


class Handler(BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        fn = self.routes.get(self.path)
        if fn is None:
            self.send_response(404)
            self.end_headers()
            return
        fn(self)

    def log_message(self, fmt, *args):
        return


class TestHTTPDownloadSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shiftbench_http_sem_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _start(self, routes):
        Handler.routes = routes
        srv = HTTPServer(("127.0.0.1", 0), Handler)
        host, port = srv.server_address
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return f"http://{host}:{port}"

    def test_missing_size_metadata_rejected(self):
        body = b"abcdefgh"

        def no_length(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            # Intentionally omit Content-Length
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/nolength": no_length})
        dest = Path(self.tmp) / "x.bin"

        with self.assertRaises(SBError) as ctx:
            stream_download(f"{base}/nolength", dest, max_attempts=1, expected_size_bytes=None)

        self.assertEqual(ctx.exception.code, E_TRUNCATED_DOWNLOAD)
        self.assertFalse(dest.exists())

    def test_200_on_range_resets_partial_and_succeeds(self):
        body = b"0123456789"

        def always_200(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/asset": always_200})
        dest = Path(self.tmp) / "asset.bin"
        partial = dest.with_suffix(dest.suffix + ".partial")
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(body[:4])

        res = stream_download(f"{base}/asset", dest, max_attempts=2, expected_size_bytes=len(body))
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), body)
        self.assertFalse(partial.exists())
        self.assertEqual(res.size_bytes, len(body))

    def test_429_retry_after_not_capped(self):
        body = b"hello world"
        calls = {"n": 0}

        def rate_then_ok(handler):
            calls["n"] += 1
            if calls["n"] == 1:
                handler.send_response(429)
                handler.send_header("Retry-After", "120")
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/r": rate_then_ok})
        dest = Path(self.tmp) / "ra.bin"

        sleep_calls = []
        with mock.patch("shiftbench.http.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            res = stream_download(f"{base}/r", dest, max_attempts=2, expected_size_bytes=len(body))

        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), body)
        self.assertEqual(int(sleep_calls[0]), 120)
        self.assertEqual(res.size_bytes, len(body))

    def test_follows_302_redirect_and_validates_size(self):
        body = b"redirected-bytes"

        def redirect(handler):
            handler.send_response(302)
            handler.send_header("Location", "/real")
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        def real(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/redir": redirect, "/real": real})
        dest = Path(self.tmp) / "redir.bin"

        with mock.patch("shiftbench.http.time.sleep") as sleep:
            res = stream_download(f"{base}/redir", dest, max_attempts=1, expected_size_bytes=len(body))

        sleep.assert_not_called()
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), body)
        self.assertEqual(res.size_bytes, len(body))

    def test_truncated_content_length_rejected(self):
        body = b"abcd"

        def truncated(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body) + 5))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/t": truncated})
        dest = Path(self.tmp) / "t.bin"
        with self.assertRaises(SBError) as ctx:
            stream_download(f"{base}/t", dest, max_attempts=1)
        self.assertEqual(ctx.exception.code, E_TRUNCATED_DOWNLOAD)
        self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
