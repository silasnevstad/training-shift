import threading
import tempfile
import shutil
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from shiftbench.errors import SBError, E_TRUNCATED_DOWNLOAD
from shiftbench.http import stream_download


class RangeHandler(BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        handler = self.routes.get(self.path)
        if handler:
            handler(self)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return


class TestStreamDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shiftbench_http_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _start(self, routes):
        RangeHandler.routes = routes
        srv = HTTPServer(("127.0.0.1", 0), RangeHandler)
        host, port = srv.server_address
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return f"http://{host}:{port}"

    def test_truncated_response_rejected(self):
        body = b"abcd"

        def truncated(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body) + 5))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/truncated": truncated})
        dest = Path(self.tmp) / "file.bin"

        with self.assertRaises(SBError) as ctx:
            stream_download(f"{base}/truncated", dest, max_attempts=1)
        self.assertEqual(ctx.exception.code, E_TRUNCATED_DOWNLOAD)
        self.assertFalse(dest.exists())

    def test_resume_invalid_content_range_fails(self):
        body = b"abcdefghij"

        def resume_invalid(handler):
            if handler.headers.get("Range"):
                handler.send_response(206)
                handler.send_header("Content-Type", "application/octet-stream")
                handler.send_header("Content-Range", "bytes 0-4/10")
                handler.send_header("Content-Length", "5")
                handler.end_headers()
                handler.wfile.write(body[:5])
                return
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/range": resume_invalid})
        dest = Path(self.tmp) / "resume.bin"
        partial = dest.with_suffix(".bin.partial")
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(body[:5])

        with self.assertRaises(SBError) as ctx:
            stream_download(f"{base}/range", dest, max_attempts=1, expected_size_bytes=len(body))
        self.assertEqual(ctx.exception.code, E_TRUNCATED_DOWNLOAD)
        self.assertFalse(dest.exists())

    def test_resume_416_resets_and_retries(self):
        body = b"hello world"

        def resume_416(handler):
            if handler.headers.get("Range"):
                handler.send_response(416)
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)

        base = self._start({"/asset": resume_416})
        dest = Path(self.tmp) / "asset.bin"
        partial = dest.with_suffix(".bin.partial")
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(body[:5])

        res = stream_download(f"{base}/asset", dest, max_attempts=2, expected_size_bytes=len(body))
        self.assertEqual(res.size_bytes, len(body))
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), body)
        self.assertFalse(partial.exists())


if __name__ == "__main__":
    unittest.main()