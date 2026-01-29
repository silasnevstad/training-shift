import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
import shutil

from src.shiftbench.ingest import IngestConfig, ingest

class Handler(BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        if self.path in self.routes:
            status, headers, body = self.routes[self.path]
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return

class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shiftbench_test_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _start(self, routes):
        Handler.routes = routes
        srv = HTTPServer(("127.0.0.1", 0), Handler)
        host, port = srv.server_address
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, f"http://{host}:{port}"

    def test_nflverse_local(self):
        release = {"tag_name": "pbp",
                   "assets": [{"name": "play_by_play_2023.parquet", "browser_download_url": "", "size": 20}]}
        body = b"PAR1fakeparquet"
        routes = {}

        srv, base = self._start(routes)
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))

        release["assets"][0]["browser_download_url"] = base + "/asset/pbp2023.parquet"
        routes["/repos/nflverse/nflverse-data/releases/tags/pbp"] = (200, {"Content-Type": "application/json"}, json.dumps(release).encode("utf-8"))
        routes["/asset/pbp2023.parquet"] = (200, {"Content-Type": "application/octet-stream"}, body)

        cfg = IngestConfig(
            source="nflverse",
            ref="pbp",
            scope={"datasets": ["play_by_play_parquet"], "seasons": [2023]},
            out_dir=Path(self.tmp) / "data" / "raw",
            cache_dir=Path(self.tmp) / "data" / ".cache" / "shiftbench",
            max_parallel=2,
            dry_run=False,
            github_api_base=base,
        )
        ingest_dir = ingest(cfg)
        self.assertTrue((ingest_dir / "manifest.json").exists())
        self.assertTrue((ingest_dir / "checksums.json").exists())
        self.assertTrue((ingest_dir / "schema.json").exists())

    def test_statsbomb_local_optional_360(self):
        routes = {}
        srv, base = self._start(routes)
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))

        sha = "a" * 40
        competitions = [{"competition_id": 1, "season_id": 10}]
        matches = [{"match_id": 999}]
        events = [{"id": 1, "type": "Pass"}]
        lineups = [{"team_id": 123}]

        routes[f"/statsbomb/open-data/{sha}/data/competitions.json"] = (200, {"Content-Type": "application/json"}, json.dumps(competitions).encode("utf-8"))
        routes[f"/statsbomb/open-data/{sha}/data/matches/1/10.json"] = (200, {"Content-Type": "application/json"}, json.dumps(matches).encode("utf-8"))
        routes[f"/statsbomb/open-data/{sha}/data/events/999.json"] = (200, {"Content-Type": "application/json"}, json.dumps(events).encode("utf-8"))
        routes[f"/statsbomb/open-data/{sha}/data/lineups/999.json"] = (200, {"Content-Type": "application/json"}, json.dumps(lineups).encode("utf-8"))
        # 3-sixty route intentionally missing -> 404 optional

        cfg = IngestConfig(
            source="statsbomb-open-data",
            ref=sha,
            scope={"competition_ids": [1], "season_ids": [10]},
            out_dir=Path(self.tmp) / "data" / "raw",
            cache_dir=Path(self.tmp) / "data" / ".cache" / "shiftbench",
            max_parallel=4,
            dry_run=False,
            github_raw_base=base,
            github_api_base=base,
        )
        ingest_dir = ingest(cfg)
        man = json.loads((ingest_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(man["results"]["status"], ["partial", "success"])
        self.assertTrue((ingest_dir / "downloads" / f"statsbomb-open-data/{sha}/events/999.json").exists())

if __name__ == "__main__":
    unittest.main()
