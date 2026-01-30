import unittest

from shiftbench.util import scope_fingerprint, normalize_scope_obj
from shiftbench.sources.nflverse import NFLVerseResolver
from shiftbench.github import GitHubClient
from shiftbench.errors import SBError, E_AMBIGUOUS_MATCH, E_ASSET_MISSING

class FakeGitHub(GitHubClient):
    def __init__(self, release_payload):
        super().__init__(api_base="http://example.invalid", cache_dir=None)
        self._release_payload = release_payload

    def get_release_by_tag(self, owner: str, repo: str, tag: str):
        return {"data": self._release_payload, "headers": {}}

class TestScopeFingerprint(unittest.TestCase):
    def test_deterministic(self):
        a = {"datasets": ["pbp_any"], "seasons": [2023, 2022]}
        b = {"seasons": [2022, 2023], "datasets": ["pbp_any"]}
        self.assertEqual(scope_fingerprint(normalize_scope_obj(a)), scope_fingerprint(normalize_scope_obj(b)))

class TestNFLVerseResolver(unittest.TestCase):
    def test_ambiguous(self):
        release = {
            "tag_name": "pbp",
            "assets": [
                {"name": "play_by_play_2023.parquet", "browser_download_url": "http://x/1", "size": 10},
                {"name": "play_by_play_2023.csv", "browser_download_url": "http://x/2", "size": 10},
            ],
        }
        r = NFLVerseResolver(FakeGitHub(release))
        with self.assertRaises(SBError) as ctx:
            r.resolve("pbp", {"datasets": ["pbp_any"], "seasons": [2023]})
        self.assertEqual(ctx.exception.code, E_AMBIGUOUS_MATCH)

    def test_missing_fatal(self):
        release = {"tag_name": "pbp", "assets": [{"name": "play_by_play_2022.csv", "browser_download_url": "http://x/1", "size": 10}]}
        r = NFLVerseResolver(FakeGitHub(release))
        with self.assertRaises(SBError) as ctx:
            r.resolve("pbp", {"datasets": ["pbp_any"], "seasons": [2023]})
        self.assertEqual(ctx.exception.code, E_ASSET_MISSING)

    def test_missing_allow(self):
        release = {"tag_name": "pbp", "assets": [{"name": "play_by_play_2022.csv", "browser_download_url": "http://x/1", "size": 10}]}
        r = NFLVerseResolver(FakeGitHub(release))
        tag, plan = r.resolve("pbp", {"datasets": ["pbp_any"], "seasons": [2023]}, allow_missing=True)
        self.assertEqual(tag, "pbp")
        self.assertEqual(len(plan), 0)

if __name__ == "__main__":
    unittest.main()
