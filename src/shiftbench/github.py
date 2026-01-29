from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import SBError, E_HTTP_403, E_HTTP_429, E_REF_NOT_FOUND, E_CONNECTION, E_TIMEOUT
from .util import canonical_json, atomic_write_text

def _rate_info(headers: Any) -> Dict[str, Any]:
    def g(k: str) -> Optional[str]:
        try:
            return headers.get(k)
        except Exception:
            return None
    return {
        "x_ratelimit_remaining": g("X-RateLimit-Remaining"),
        "x_ratelimit_reset": g("X-RateLimit-Reset"),
        "x_ratelimit_limit": g("X-RateLimit-Limit"),
    }

@dataclass
class GitHubClient:
    api_base: str = "https://api.github.com"
    token_env: str = "GITHUB_TOKEN"
    cache_dir: Optional[Path] = None
    timeout_s: float = 20.0
    user_agent: str = "shiftbench/0.1.0"

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "User-Agent": self.user_agent}
        tok = os.getenv(self.token_env)
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.cache_dir:
            return None
        p = self.cache_dir / (key + ".json")
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _cache_put(self, key: str, obj: Dict[str, Any]) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        p = self.cache_dir / (key + ".json")
        atomic_write_text(p, canonical_json(obj))

    def _get_json(self, url: str, cache_key: Optional[str] = None) -> Dict[str, Any]:
        if cache_key:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read()
                data = json.loads(body.decode("utf-8"))
                out = {"data": data, "headers": dict(resp.headers)}
                if cache_key:
                    self._cache_put(cache_key, out)
                return out
        except urllib.error.HTTPError as e:
            hdrs = e.headers or {}
            if e.code in (403, 429):
                code = E_HTTP_429 if e.code == 429 else E_HTTP_403
                raise SBError(code, f"GitHub API HTTP {e.code}", detail={"body": e.read().decode("utf-8", "ignore"), "rate": _rate_info(hdrs)}, url=url, retryable=(e.code == 429), severity="error")
            if e.code == 404:
                raise SBError(E_REF_NOT_FOUND, "GitHub API resource not found", detail={"body": e.read().decode("utf-8", "ignore")}, url=url, retryable=False, severity="fatal")
            raise SBError(f"E_HTTP_{e.code}", f"GitHub API HTTP {e.code}", detail={"body": e.read().decode("utf-8", "ignore")}, url=url, retryable=False, severity="error")
        except urllib.error.URLError as e:
            msg = str(e.reason) if hasattr(e, "reason") else str(e)
            is_timeout = "timed out" in msg.lower()
            raise SBError(E_TIMEOUT if is_timeout else E_CONNECTION, "GitHub API network error", detail=msg, url=url, retryable=True, severity="error")

    def get_release_by_tag(self, owner: str, repo: str, tag: str) -> Dict[str, Any]:
        url = f"{self.api_base}/repos/{owner}/{repo}/releases/tags/{tag}"
        key = f"release_{owner}_{repo}_{tag}"
        return self._get_json(url, cache_key=key)

    def resolve_ref_to_commit(self, owner: str, repo: str, ref: str) -> str:
        url = f"{self.api_base}/repos/{owner}/{repo}/commits/{ref}"
        key = f"commit_{owner}_{repo}_{ref}"
        out = self._get_json(url, cache_key=key)
        data = out.get("data") or {}
        sha = data.get("sha")
        if not sha:
            raise SBError(E_REF_NOT_FOUND, "Unable to resolve ref to commit SHA", detail={"ref": ref}, url=url, retryable=False, severity="fatal")
        return str(sha)
