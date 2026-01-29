from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..errors import SBError, E_SCOPE_INVALID, E_FLOATING_REF_DISALLOWED
from ..github import GitHubClient
from ..util import is_probably_commit_sha

@dataclass
class PlanItem:
    logical_name: str
    url: str
    dest_path: str
    expected_type: str
    expected_size_bytes: Optional[int]
    sha256: Optional[str]
    group: str
    competition_id: Optional[int] = None
    season_id: Optional[int] = None
    match_id: Optional[int] = None
    optional: bool = False

def _raw_url(owner: str, repo: str, sha: str, path: str, *, raw_base: str) -> str:
    return f"{raw_base}/{owner}/{repo}/{sha}/{path}"

class StatsBombOpenDataResolver:
    def __init__(self, gh: GitHubClient, *, owner: str = "statsbomb", repo: str = "open-data", raw_base: str = "https://raw.githubusercontent.com"):
        self.gh = gh
        self.owner = owner
        self.repo = repo
        self.raw_base = raw_base

    def resolve(self, ref: str, scope: Dict[str, Any], *, allow_floating: bool = False) -> Tuple[str, List[PlanItem]]:
        if is_probably_commit_sha(ref) and len(ref.strip()) == 40:
            commit_sha = ref.strip()
        else:
            if not allow_floating:
                raise SBError(E_FLOATING_REF_DISALLOWED, "Floating ref disallowed for statsbomb-open-data; use a commit SHA", detail={"ref": ref}, retryable=False, severity="fatal")
            commit_sha = self.gh.resolve_ref_to_commit(self.owner, self.repo, ref)

        plan: List[PlanItem] = []
        # Always include competitions.json
        plan.append(PlanItem(
            logical_name="competitions",
            url=_raw_url(self.owner, self.repo, commit_sha, "data/competitions.json", raw_base=self.raw_base),
            dest_path=f"statsbomb-open-data/{commit_sha}/competitions.json",
            expected_type="json",
            expected_size_bytes=None,
            sha256=None,
            group="competitions",
            optional=False,
        ))

        # Two-phase expansion: ingest downloads competitions.json first, then expands pairs/matches/match artifacts.
        plan.append(PlanItem(
            logical_name="__deferred__",
            url="",
            dest_path="",
            expected_type="unknown",
            expected_size_bytes=None,
            sha256=None,
            group="__deferred__",
            optional=True,
        ))
        return commit_sha, plan

    def expand_pairs_from_competitions(self, competitions_json_path, scope: Dict[str, Any]) -> List[Tuple[int, int]]:
        data = json.loads(competitions_json_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SBError(E_SCOPE_INVALID, "competitions.json not a list", detail={"type": str(type(data))}, retryable=False, severity="fatal")
        comp_ids = scope.get("competition_ids")
        season_ids = scope.get("season_ids")
        pairs_scope = scope.get("competition_season_ids")
        if pairs_scope is not None:
            pairs = []
            for p in pairs_scope:
                pairs.append((int(p["competition_id"]), int(p["season_id"])))
            pairs = sorted(set(pairs))
            if not pairs:
                raise SBError(E_SCOPE_INVALID, "No competition_season_ids provided", detail=scope, retryable=False, severity="fatal")
            return pairs

        if comp_ids is None and season_ids is None:
            raise SBError(E_SCOPE_INVALID, "Provide competition_season_ids or competition_ids/season_ids filters", detail=scope, retryable=False, severity="fatal")
        comp_set = set(int(x) for x in comp_ids) if isinstance(comp_ids, list) else None
        season_set = set(int(x) for x in season_ids) if isinstance(season_ids, list) else None
        pairs = []
        for row in data:
            if not isinstance(row, dict):
                continue
            cid = row.get("competition_id")
            sid = row.get("season_id")
            if cid is None or sid is None:
                continue
            cid = int(cid); sid = int(sid)
            if comp_set is not None and cid not in comp_set:
                continue
            if season_set is not None and sid not in season_set:
                continue
            pairs.append((cid, sid))
        pairs = sorted(set(pairs))
        if not pairs:
            raise SBError(E_SCOPE_INVALID, "No competition/season pairs matched filters", detail=scope, retryable=False, severity="fatal")
        return pairs

    def plan_matches_files(self, commit_sha: str, pairs: List[Tuple[int, int]]) -> List[PlanItem]:
        items: List[PlanItem] = []
        for cid, sid in pairs:
            p = f"data/matches/{cid}/{sid}.json"
            items.append(PlanItem(
                logical_name=f"matches_{cid}_{sid}",
                url=_raw_url(self.owner, self.repo, commit_sha, p, raw_base=self.raw_base),
                dest_path=f"statsbomb-open-data/{commit_sha}/matches/{cid}/{sid}.json",
                expected_type="json",
                expected_size_bytes=None,
                sha256=None,
                group="matches",
                competition_id=cid,
                season_id=sid,
                optional=False,
            ))
        return items

    def extract_match_ids(self, matches_json_path) -> List[int]:
        data = json.loads(matches_json_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        mids = []
        for row in data:
            if isinstance(row, dict):
                if "match_id" in row:
                    mids.append(int(row["match_id"]))
                elif "id" in row:
                    mids.append(int(row["id"]))
        return sorted(set(mids))

    def plan_match_artifacts(self, commit_sha: str, match_ids: List[int]) -> List[PlanItem]:
        items: List[PlanItem] = []
        for mid in match_ids:
            items.append(PlanItem(
                logical_name=f"events_{mid}",
                url=_raw_url(self.owner, self.repo, commit_sha, f"data/events/{mid}.json", raw_base=self.raw_base),
                dest_path=f"statsbomb-open-data/{commit_sha}/events/{mid}.json",
                expected_type="json",
                expected_size_bytes=None,
                sha256=None,
                group="events",
                match_id=mid,
                optional=False,
            ))
            items.append(PlanItem(
                logical_name=f"lineups_{mid}",
                url=_raw_url(self.owner, self.repo, commit_sha, f"data/lineups/{mid}.json", raw_base=self.raw_base),
                dest_path=f"statsbomb-open-data/{commit_sha}/lineups/{mid}.json",
                expected_type="json",
                expected_size_bytes=None,
                sha256=None,
                group="lineups",
                match_id=mid,
                optional=False,
            ))
            items.append(PlanItem(
                logical_name=f"three_sixty_{mid}",
                url=_raw_url(self.owner, self.repo, commit_sha, f"data/three-sixty/{mid}.json", raw_base=self.raw_base),
                dest_path=f"statsbomb-open-data/{commit_sha}/three-sixty/{mid}.json",
                expected_type="json",
                expected_size_bytes=None,
                sha256=None,
                group="three-sixty",
                match_id=mid,
                optional=True,
            ))
        return items
