import unittest

from shiftbench.sources.nflverse import NFLVerseResolver
from shiftbench.github import GitHubClient
from shiftbench.errors import SBError, E_AMBIGUOUS_MATCH


class FakeGitHub(GitHubClient):
    def __init__(self, release_payload):
        super().__init__(api_base="http://example.invalid", cache_dir=None)
        self._release_payload = release_payload

    def get_release_by_tag(self, owner: str, repo: str, tag: str):
        return {"data": self._release_payload, "headers": {}}


class TestNFLVerseResolverMore(unittest.TestCase):
    def test_play_by_play_defaults_to_parquet_when_both_exist(self):
        release = {
            "tag_name": "pbp",
            "assets": [
                {"name": "play_by_play_2023.parquet", "browser_download_url": "http://x/pq", "size": 10},
                {"name": "play_by_play_2023.csv", "browser_download_url": "http://x/csv", "size": 10},
            ],
        }
        r = NFLVerseResolver(FakeGitHub(release))
        tag, plan = r.resolve("pbp", {"datasets": ["play_by_play"], "seasons": [2023]})
        self.assertEqual(tag, "pbp")
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0].url.endswith("/pq"))
        self.assertTrue(plan[0].dest_path.endswith(".parquet"))

    def test_play_by_play_csv_selects_csv(self):
        release = {
            "tag_name": "pbp",
            "assets": [
                {"name": "play_by_play_2023.parquet", "browser_download_url": "http://x/pq", "size": 10},
                {"name": "play_by_play_2023.csv", "browser_download_url": "http://x/csv", "size": 10},
            ],
        }
        r = NFLVerseResolver(FakeGitHub(release))
        tag, plan = r.resolve("pbp", {"datasets": ["play_by_play_csv"], "seasons": [2023]})
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0].url.endswith("/csv"))
        self.assertTrue(plan[0].dest_path.endswith(".csv"))

    def test_any_is_ambiguous(self):
        release = {
            "tag_name": "pbp",
            "assets": [
                {"name": "play_by_play_2023.parquet", "browser_download_url": "http://x/pq", "size": 10},
                {"name": "play_by_play_2023.csv", "browser_download_url": "http://x/csv", "size": 10},
            ],
        }
        r = NFLVerseResolver(FakeGitHub(release))
        with self.assertRaises(SBError) as ctx:
            r.resolve("pbp", {"datasets": ["play_by_play_any"], "seasons": [2023]})
        self.assertEqual(ctx.exception.code, E_AMBIGUOUS_MATCH)


if __name__ == "__main__":
    unittest.main()
