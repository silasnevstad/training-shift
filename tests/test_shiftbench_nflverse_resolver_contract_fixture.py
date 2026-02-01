import json
import unittest
from pathlib import Path

from shiftbench.errors import SBError, E_AMBIGUOUS_MATCH
from shiftbench.github import GitHubClient
from shiftbench.sources.nflverse import NFLVerseResolver


class FakeGitHub(GitHubClient):
    def __init__(self, release_payload):
        super().__init__(api_base="http://example.invalid", cache_dir=None)
        self._release_payload = release_payload

    def get_release_by_tag(self, owner: str, repo: str, tag: str):
        return {"data": self._release_payload, "headers": {}}


class TestNFLVerseResolverContractFixture(unittest.TestCase):
    def _load_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "nflverse_release_pbp_fixture.json"
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_fixture_default_selects_parquet_and_formats_dest_path(self):
        release = self._load_fixture()
        r = NFLVerseResolver(FakeGitHub(release))
        tag, plan = r.resolve("pbp", {"datasets": ["play_by_play"], "seasons": [2023]})
        self.assertEqual(tag, "pbp")
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0].url.endswith(".parquet"))
        self.assertTrue(plan[0].dest_path.endswith("/play_by_play_2023.parquet"))
        self.assertIn("/play_by_play/", plan[0].dest_path)

    def test_fixture_csv_selects_csv(self):
        release = self._load_fixture()
        r = NFLVerseResolver(FakeGitHub(release))
        tag, plan = r.resolve("pbp", {"datasets": ["play_by_play_csv"], "seasons": [2023]})
        self.assertEqual(tag, "pbp")
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0].url.endswith(".csv"))
        self.assertTrue(plan[0].dest_path.endswith("/play_by_play_2023.csv"))
        self.assertIn("/play_by_play_csv/", plan[0].dest_path)

    def test_fixture_any_is_ambiguous(self):
        release = self._load_fixture()
        r = NFLVerseResolver(FakeGitHub(release))
        with self.assertRaises(SBError) as ctx:
            r.resolve("pbp", {"datasets": ["play_by_play_any"], "seasons": [2023]})
        self.assertEqual(ctx.exception.code, E_AMBIGUOUS_MATCH)


if __name__ == "__main__":
    unittest.main()
