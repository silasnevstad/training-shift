import json
import tempfile
import shutil
import unittest
from pathlib import Path

from shiftbench.ingest import verify_ingestion_integrity
from shiftbench.errors import (
    E_REQUIRED_ASSET_MISSING,
    E_CHECKSUM_RECORD_MISSING,
)


class TestIntegrityPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shiftbench_integrity_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_require_360_does_not_require_other_optional_groups(self):
        ingest_dir = Path(self.tmp) / "ingest"
        downloads_dir = ingest_dir / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        # Required file exists + checksummed
        required_dest = "statsbomb-open-data/sha/events/1.json"
        required_path = downloads_dir / required_dest
        required_path.parent.mkdir(parents=True, exist_ok=True)
        required_path.write_bytes(b'{"ok":true}\n')

        import hashlib
        sha = hashlib.sha256(required_path.read_bytes()).hexdigest()

        manifest = {
            "source": "statsbomb-open-data",
            "source_ref": "a" * 40,
            "config": {"require_360": True},
            "resolved_plan": [
                {"logical_name": "events_1", "dest_path": required_dest, "group": "events", "optional": False},
                # Optional non-360 item missing: must remain non-gating even when require_360=True
                {"logical_name": "optional_x", "dest_path": "statsbomb-open-data/sha/optional/x.json", "group": "optional-group", "optional": True},
                # 360 item missing: should be required under require_360=True (and thus fail)
                {"logical_name": "three_sixty_1", "dest_path": "statsbomb-open-data/sha/three-sixty/1.json", "group": "three-sixty", "optional": True},
            ],
        }
        checksums = {required_dest: {"sha256": sha, "size_bytes": required_path.stat().st_size, "mtime_utc": "x"}}

        (ingest_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (ingest_dir / "checksums.json").write_text(json.dumps(checksums), encoding="utf-8")

        ok, errs = verify_ingestion_integrity(ingest_dir)
        self.assertFalse(ok)
        codes = [e.get("code") for e in errs]
        self.assertIn(E_REQUIRED_ASSET_MISSING, codes)
        self.assertIn(E_CHECKSUM_RECORD_MISSING, codes)

        # Critically: should NOT fail because "optional_x" is missing (non-360 optional).
        # We validate by checking that the missing required is the 360 path, not the optional-group path.
        missing_paths = [e.get("detail", {}).get("dest_path") for e in errs if e.get("code") in (E_REQUIRED_ASSET_MISSING, E_CHECKSUM_RECORD_MISSING)]
        self.assertIn("statsbomb-open-data/sha/three-sixty/1.json", missing_paths)
        self.assertNotIn("statsbomb-open-data/sha/optional/x.json", missing_paths)


if __name__ == "__main__":
    unittest.main()
