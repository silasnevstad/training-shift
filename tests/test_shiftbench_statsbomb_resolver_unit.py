import json
import tempfile
import shutil
import unittest
from pathlib import Path

from shiftbench.sources.statsbomb_open_data import StatsBombOpenDataResolver
from shiftbench.github import GitHubClient
from shiftbench.errors import SBError, E_SCOPE_INVALID, E_JSON_PARSE, E_ASSET_MISSING


class FakeGitHub(GitHubClient):
    def __init__(self):
        super().__init__(api_base="http://example.invalid", cache_dir=None)

    def resolve_ref_to_commit(self, owner: str, repo: str, ref: str) -> str:
        return "a" * 40


class TestStatsBombResolverUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shiftbench_statsbomb_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_expand_pairs_from_competitions_missing_file(self):
        r = StatsBombOpenDataResolver(FakeGitHub(), raw_base="http://example.invalid")
        p = Path(self.tmp) / "missing.json"
        with self.assertRaises(SBError) as ctx:
            r.expand_pairs_from_competitions(p, {"competition_ids": [1]})
        self.assertEqual(ctx.exception.code, E_ASSET_MISSING)

    def test_expand_pairs_invalid_json(self):
        r = StatsBombOpenDataResolver(FakeGitHub(), raw_base="http://example.invalid")
        p = Path(self.tmp) / "competitions.json"
        p.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(SBError) as ctx:
            r.expand_pairs_from_competitions(p, {"competition_ids": [1]})
        self.assertEqual(ctx.exception.code, E_JSON_PARSE)

    def test_expand_pairs_requires_filters_or_pairs(self):
        r = StatsBombOpenDataResolver(FakeGitHub(), raw_base="http://example.invalid")
        p = Path(self.tmp) / "competitions.json"
        p.write_text(json.dumps([{"competition_id": 1, "season_id": 10}]), encoding="utf-8")
        with self.assertRaises(SBError) as ctx:
            r.expand_pairs_from_competitions(p, {})
        self.assertEqual(ctx.exception.code, E_SCOPE_INVALID)

    def test_expand_pairs_competition_season_ids_validation(self):
        r = StatsBombOpenDataResolver(FakeGitHub(), raw_base="http://example.invalid")
        p = Path(self.tmp) / "competitions.json"
        p.write_text(json.dumps([{"competition_id": 1, "season_id": 10}]), encoding="utf-8")

        # malformed entry missing season_id
        with self.assertRaises(SBError) as ctx:
            r.expand_pairs_from_competitions(p, {"competition_season_ids": [{"competition_id": 1}]})
        self.assertEqual(ctx.exception.code, E_SCOPE_INVALID)

    def test_expand_pairs_filters_match(self):
        r = StatsBombOpenDataResolver(FakeGitHub(), raw_base="http://example.invalid")
        p = Path(self.tmp) / "competitions.json"
        p.write_text(
            json.dumps(
                [
                    {"competition_id": 1, "season_id": 10},
                    {"competition_id": 2, "season_id": 20},
                ]
            ),
            encoding="utf-8",
        )
        pairs = r.expand_pairs_from_competitions(p, {"competition_ids": [1]})
        self.assertEqual(pairs, [(1, 10)])


    def test_extract_match_ids_supports_match_id_and_id(self):
        r = StatsBombOpenDataResolver(FakeGitHub(), raw_base="http://example.invalid")
        p = Path(self.tmp) / "matches.json"
        p.write_text(
            json.dumps(
                [
                    {"match_id": 1},
                    {"id": 2},
                    {"match_id": 1},  # duplicate
                ]
            ),
            encoding="utf-8",
        )
        mids = r.extract_match_ids(p)
        self.assertEqual(mids, [1, 2])


if __name__ == "__main__":
    unittest.main()
