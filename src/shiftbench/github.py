from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import SBError, E_CONNECTION, E_HTTP_403, E_HTTP_429, E_REF_NOT_FOUND, E_TIMEOUT
from .util import atomic_write_text, canonical_json


def _debug_enabled() -> bool:
    v = os.getenv("SHIFTBENCH_DEBUG", "")
    return v.strip().lower() in ("1", "true", "yes", "on")


def _dbg(event: str, **fields: Any) -> None:
    if not _debug_enabled():
        return
    payload = {"ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "component": "shiftbench.github", "event": event}
    payload.update(fields)
    sys.stderr.write(json.dumps(payload, sort_keys=True) + "\n")


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


def _parse_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _parse_retry_after_seconds(headers: Any, *, now_s: float) -> Optional[int]:
    """
    Retry-After is typically integer seconds, but HTTP spec allows HTTP-date.
    """
    try:
        raw = headers.get("Retry-After")
    except Exception:
        raw = None

    if raw is None:
        return None

    raw = str(raw).strip()
    if not raw:
        return None

    # integer seconds
    try:
        n = int(raw)
        return max(0, n)
    except Exception:
        pass

    # HTTP-date
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            # Assume UTC if tz missing
            dt = dt.replace(tzinfo=parsedate_to_datetime("Thu, 01 Jan 1970 00:00:00 GMT").tzinfo)
        return max(0, int(dt.timestamp() - now_s))
    except Exception:
        return None


def _compute_backoff_s(attempt: int, *, base: float, factor: float, jitter: float, max_delay: float) -> float:
    delay = min(max_delay, base * (factor ** max(0, attempt - 1)))
    if jitter <= 0:
        return delay
    j = 1.0 + random.uniform(-jitter, jitter)
    return max(0.0, delay * j)


def _looks_like_rate_limit_message(body_text: str) -> bool:
    t = (body_text or "").lower()
    return ("secondary rate limit" in t) or ("rate limit exceeded" in t)


@dataclass
class GitHubClient:
    api_base: str = "https://api.github.com"
    token_env: str = "GITHUB_TOKEN"
    cache_dir: Optional[Path] = None
    timeout_s: float = 20.0
    user_agent: str = "shiftbench/0.1.0"

    # recommended header; default on GitHub is currently 2022-11-28 if omitted
    api_version: str = "2022-11-28"

    # retry policy
    max_attempts: int = 5
    max_backoff_s: float = 600.0
    min_rate_limit_wait_s: float = 60.0

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": self.api_version,
        }
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
                _dbg("cache_hit", url=url, cache_key=cache_key)
                return cached

        def _sleep_s(seconds: float) -> None:
            _dbg("sleep", seconds=float(seconds), url=url)
            time.sleep(max(0.0, float(seconds)))

        attempt = 0
        last_err: Optional[SBError] = None

        while attempt < max(1, int(self.max_attempts)):
            attempt += 1
            headers = self._headers()
            _dbg("request", attempt=attempt, url=url, headers=headers)

            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    body = resp.read()
                    data = json.loads(body.decode("utf-8"))
                    out = {"data": data, "headers": dict(resp.headers)}
                    _dbg("response_ok", attempt=attempt, url=url, status=int(getattr(resp, "status", 0) or 0), resp_headers=dict(resp.headers))
                    if cache_key:
                        self._cache_put(cache_key, out)
                    return out

            except urllib.error.HTTPError as e:
                hdrs = e.headers or {}
                status = int(getattr(e, "code", 0) or 0)
                try:
                    body_bytes = e.read() or b""
                except Exception:
                    body_bytes = b""
                body_text = body_bytes.decode("utf-8", "ignore")

                rate = _rate_info(hdrs)
                remaining = _parse_int(rate.get("x_ratelimit_remaining"))
                reset_epoch = _parse_int(rate.get("x_ratelimit_reset"))
                now_s = time.time()
                retry_after_s = _parse_retry_after_seconds(hdrs, now_s=now_s)

                _dbg(
                    "response_error",
                    attempt=attempt,
                    url=url,
                    status=status,
                    retry_after_seconds=retry_after_s,
                    ratelimit=rate,
                    body_preview=body_text[:200],
                )

                def is_rate_limited() -> bool:
                    if status == 429:
                        return True
                    if status != 403:
                        return False
                    if retry_after_s is not None:
                        return True
                    if remaining == 0:
                        return True
                    return _looks_like_rate_limit_message(body_text)

                def compute_wait_s() -> float:
                    if retry_after_s is not None and retry_after_s > 0:
                        return float(retry_after_s)
                    if remaining == 0 and reset_epoch is not None:
                        return max(0.0, float(reset_epoch - int(now_s) + 1))
                    base = float(self.min_rate_limit_wait_s)
                    return _compute_backoff_s(attempt, base=base, factor=2.0, jitter=0.1, max_delay=float(self.max_backoff_s))

                if status == 404:
                    raise SBError(
                        E_REF_NOT_FOUND,
                        "GitHub API resource not found",
                        detail={"body": body_text, "rate": rate},
                        url=url,
                        retryable=False,
                        severity="fatal",
                    )

                if is_rate_limited():
                    wait_s = compute_wait_s()
                    last_err = SBError(
                        E_HTTP_429 if status == 429 else E_HTTP_403,
                        f"GitHub API HTTP {status} (rate limited)",
                        detail={
                            "body": body_text,
                            "rate": rate,
                            "retry_after_seconds": retry_after_s,
                            "classified_as_rate_limit": True,
                            "wait_seconds": float(wait_s),
                        },
                        url=url,
                        retryable=True,
                        severity="error",
                    )
                    if attempt < self.max_attempts:
                        _sleep_s(wait_s)
                        continue
                    raise last_err

                # non-rate-limit 403 should not be retried
                if status == 403:
                    raise SBError(
                        E_HTTP_403,
                        "GitHub API HTTP 403",
                        detail={"body": body_text, "rate": rate, "classified_as_rate_limit": False},
                        url=url,
                        retryable=False,
                        severity="error",
                    )

                if status == 429:
                    # defensive
                    raise SBError(
                        E_HTTP_429,
                        "GitHub API HTTP 429",
                        detail={"body": body_text, "rate": rate, "retry_after_seconds": retry_after_s},
                        url=url,
                        retryable=True,
                        severity="error",
                    )

                raise SBError(
                    f"E_HTTP_{status}",
                    f"GitHub API HTTP {status}",
                    detail={"body": body_text, "rate": rate},
                    url=url,
                    retryable=False,
                    severity="error",
                )

            except urllib.error.URLError as e:
                msg = str(e.reason) if hasattr(e, "reason") else str(e)
                is_timeout = "timed out" in msg.lower()
                last_err = SBError(
                    E_TIMEOUT if is_timeout else E_CONNECTION,
                    "GitHub API network error",
                    detail=msg,
                    url=url,
                    retryable=True,
                    severity="error",
                )
                _dbg("network_error", attempt=attempt, url=url, error=msg, timeout=is_timeout)
                if attempt < self.max_attempts:
                    wait_s = _compute_backoff_s(attempt, base=1.0, factor=2.0, jitter=0.1, max_delay=30.0)
                    _sleep_s(wait_s)
                    continue
                raise last_err

        raise last_err or SBError(
            E_CONNECTION,
            "GitHub API request failed",
            detail={"url": url},
            url=url,
            retryable=False,
            severity="fatal",
        )

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
            raise SBError(
                E_REF_NOT_FOUND,
                "Unable to resolve ref to commit SHA",
                detail={"ref": ref},
                url=url,
                retryable=False,
                severity="fatal",
            )
        return str(sha)
