from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..errors import SBError, E_SCOPE_INVALID, E_REF_NOT_FOUND, E_ASSET_MISSING, E_AMBIGUOUS_MATCH
from ..github import GitHubClient


@dataclass
class PlanItem:
    logical_name: str
    url: str
    dest_path: str
    expected_type: str
    expected_size_bytes: Optional[int]
    sha256: Optional[str]
    group: str
    season: Optional[int] = None


def _expected_type(name: str) -> str:
    n = name.lower()
    if n.endswith(".parquet"):
        return "parquet"
    if n.endswith(".csv"):
        return "csv"
    if n.endswith(".json"):
        return "json"
    if n.endswith(".zip"):
        return "zip"
    if n.endswith(".tar") or n.endswith(".tar.gz") or n.endswith(".tgz"):
        return "tar"
    return "unknown"


class NFLVerseResolver:
    def __init__(self, gh: GitHubClient, *, owner: str = "nflverse", repo: str = "nflverse-data"):
        self.gh = gh
        self.owner = owner
        self.repo = repo

    def resolve(self, ref: str, scope: Dict[str, Any], *, allow_missing: bool = False) -> Tuple[str, List[PlanItem]]:
        datasets = scope.get("datasets")
        seasons = scope.get("seasons")
        if not isinstance(datasets, list) or not datasets:
            raise SBError(E_SCOPE_INVALID, "nflverse scope must include datasets list", detail=scope, retryable=False,
                          severity="fatal")
        if not isinstance(seasons, list) or not seasons:
            raise SBError(E_SCOPE_INVALID, "nflverse scope must include seasons list", detail=scope, retryable=False,
                          severity="fatal")

        season_years: List[int] = []
        for s in seasons:
            try:
                season_years.append(int(s))
            except Exception:
                raise SBError(E_SCOPE_INVALID, "Invalid season year", detail={"season": s}, retryable=False,
                              severity="fatal")
        season_years = sorted(set(season_years))

        # Deterministic format selection:
        # - default `play_by_play` / `pbp` => parquet
        # - opt-in csv via `play_by_play_csv` / `pbp_csv`
        # - `*_any` exists only for debugging and should remain ambiguous if both exist
        patterns: Dict[str, str] = {
            "play_by_play": r"^play_by_play_(\d{4})\.parquet$",
            "pbp": r"^play_by_play_(\d{4})\.parquet$",
            "play_by_play_parquet": r"^play_by_play_(\d{4})\.parquet$",
            "pbp_parquet": r"^play_by_play_(\d{4})\.parquet$",
            "play_by_play_csv": r"^play_by_play_(\d{4})\.csv$",
            "pbp_csv": r"^play_by_play_(\d{4})\.csv$",
            "play_by_play_any": r"^play_by_play_(\d{4})\.(parquet|csv)$",
            "pbp_any": r"^play_by_play_(\d{4})\.(parquet|csv)$",
        }

        rel = self.gh.get_release_by_tag(self.owner, self.repo, ref)["data"]
        tag_name = rel.get("tag_name") or ref
        assets = rel.get("assets") or []
        if not assets:
            raise SBError(E_REF_NOT_FOUND, "Release has no assets", detail={"ref": ref}, retryable=False, severity="fatal")

        plan: List[PlanItem] = []
        missing: List[Dict[str, Any]] = []

        for dataset in datasets:
            ds = str(dataset)
            if ds not in patterns:
                raise SBError(E_SCOPE_INVALID, "Unknown nflverse dataset", detail={"dataset": ds}, retryable=False,
                              severity="fatal")
            rx = re.compile(patterns[ds])
            for yr in season_years:
                matches = []
                for a in assets:
                    name = a.get("name") or ""
                    m = rx.match(name)
                    if not m:
                        continue
                    if int(m.group(1)) == yr:
                        matches.append(a)
                if len(matches) == 0:
                    missing.append({"dataset": ds, "season": yr})
                    continue
                if len(matches) > 1:
                    cand = [x.get("name") for x in matches]
                    raise SBError(E_AMBIGUOUS_MATCH, "Multiple assets match dataset/season",
                                  detail={"dataset": ds, "season": yr, "candidates": cand}, retryable=False,
                                  severity="fatal")
                a = matches[0]
                url = a.get("browser_download_url")
                name = a.get("name")
                if not url or not name:
                    raise SBError(E_REF_NOT_FOUND, "Asset missing browser_download_url/name", detail={"asset": a},
                                  retryable=False, severity="fatal")
                logical = f"{ds}_{yr}"
                dest = f"nflverse/{tag_name}/{ds}/{name}"
                plan.append(PlanItem(
                    logical_name=logical,
                    url=str(url),
                    dest_path=dest,
                    expected_type=_expected_type(name),
                    expected_size_bytes=a.get("size"),
                    sha256=None,
                    group=ds,
                    season=yr,
                ))

        if missing and not allow_missing:
            raise SBError(E_ASSET_MISSING, "Missing required nflverse assets for requested scope",
                          detail={"missing": missing}, retryable=False, severity="fatal")

        return str(tag_name), plan
