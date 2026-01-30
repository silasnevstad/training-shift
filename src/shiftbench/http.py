from __future__ import annotations

import hashlib
import os
import random
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .errors import (
    SBError,
    E_HTTP_404, E_HTTP_403, E_HTTP_429, E_TIMEOUT, E_CONNECTION, E_HTTP_5XX,
    E_TRUNCATED_DOWNLOAD, E_ATOMIC_RENAME_FAILED,
)

@dataclass
class DownloadResult:
    sha256: str
    size_bytes: int
    mtime_utc: str
    skipped: bool = False

def _http_error_to_sberr(e: urllib.error.HTTPError, url: str) -> SBError:
    code = e.code
    if code == 404:
        return SBError(E_HTTP_404, "HTTP 404", detail=str(e), url=url, retryable=False, severity="error")
    if code == 403:
        return SBError(E_HTTP_403, "HTTP 403", detail=str(e), url=url, retryable=False, severity="error")
    if code == 429:
        ra = e.headers.get("Retry-After")
        return SBError(E_HTTP_429, "HTTP 429 rate limited", detail={"error": str(e), "retry_after": ra}, url=url, retryable=True, severity="error")
    if 500 <= code <= 599:
        return SBError(E_HTTP_5XX, f"HTTP {code}", detail=str(e), url=url, retryable=True, severity="error")
    return SBError(f"E_HTTP_{code}", f"HTTP {code}", detail=str(e), url=url, retryable=False, severity="error")

def _compute_backoff(attempt: int, base: float = 1.0, factor: float = 2.0, jitter: float = 0.2, max_delay: float = 60.0) -> float:
    delay = min(max_delay, base * (factor ** (attempt - 1)))
    j = 1.0 + random.uniform(-jitter, jitter)
    return max(0.0, delay * j)

def stream_download(
    url: str,
    dest_path: Path,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 30.0,
    max_attempts: int = 5,
    resume: bool = True,
    min_size_bytes: int = 1,
    expected_size_bytes: Optional[int] = None,
) -> DownloadResult:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    partial = dest_path.with_suffix(dest_path.suffix + ".partial")

    def _parse_content_range(value: Optional[str]) -> Optional[Dict[str, Optional[int]]]:
        if not value:
            return None
        try:
            units, rng = value.split(" ", 1)
        except ValueError:
            return None
        if units.strip() != "bytes":
            return None
        try:
            range_part, total_part = rng.split("/", 1)
            start_str, end_str = range_part.split("-", 1)
            start = int(start_str)
            end = int(end_str)
        except Exception:
            return None
        total: Optional[int]
        if total_part.strip() == "*":
            total = None
        else:
            try:
                total = int(total_part)
            except Exception:
                return None
        return {"start": start, "end": end, "total": total}

    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            req_headers = dict(headers or {})
            start_at = 0
            h = hashlib.sha256()

            if resume and partial.exists():
                start_at = partial.stat().st_size
                if start_at > 0:
                    req_headers["Range"] = f"bytes={start_at}-"
                    with open(partial, "rb") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b""):
                            h.update(chunk)

            req = urllib.request.Request(url, headers=req_headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                content_length_header = resp.headers.get("Content-Length")
                try:
                    content_length = int(content_length_header) if content_length_header is not None else None
                except ValueError:
                    content_length = None
                content_range = _parse_content_range(resp.headers.get("Content-Range"))

                if start_at > 0 and resp.status == 200:
                    start_at = 0
                    h = hashlib.sha256()
                    try:
                        partial.unlink()
                    except FileNotFoundError:
                        pass
                    continue

                if start_at > 0:
                    if resp.status != 206:
                        raise SBError(
                            E_TRUNCATED_DOWNLOAD,
                            "Resume response missing 206 status",
                            detail={"status": resp.status, "start_at": start_at},
                            url=url,
                            retryable=False,
                            severity="error",
                        )
                    if not content_range:
                        raise SBError(
                            E_TRUNCATED_DOWNLOAD,
                            "Resume response missing Content-Range",
                            detail={"start_at": start_at},
                            url=url,
                            retryable=False,
                            severity="error",
                        )
                    if content_range["start"] != start_at:
                        raise SBError(
                            E_TRUNCATED_DOWNLOAD,
                            "Resume Content-Range mismatch",
                            detail={"expected_start": start_at, "actual_start": content_range["start"]},
                            url=url,
                            retryable=False,
                            severity="error",
                        )
                    if content_range["end"] < content_range["start"]:
                        raise SBError(
                            E_TRUNCATED_DOWNLOAD,
                            "Resume Content-Range invalid",
                            detail={"content_range": content_range},
                            url=url,
                            retryable=False,
                            severity="error",
                        )
                    if expected_size_bytes is not None and content_range["total"] is not None and content_range["total"] != expected_size_bytes:
                        raise SBError(
                            E_TRUNCATED_DOWNLOAD,
                            "Resume Content-Range total mismatch",
                            detail={"expected_total": expected_size_bytes, "content_range_total": content_range["total"]},
                            url=url,
                            retryable=False,
                            severity="error",
                        )

                mode = "ab" if start_at > 0 else "wb"
                bytes_written = start_at
                with open(partial, mode) as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        h.update(chunk)
                        bytes_written += len(chunk)
                    f.flush()
                    os.fsync(f.fileno())

            expected_total = expected_size_bytes
            if expected_total is None and content_range and content_range["total"] is not None:
                expected_total = content_range["total"]
            if expected_total is None and content_length is not None:
                expected_total = content_length + start_at if start_at > 0 else content_length

            if bytes_written < min_size_bytes:
                raise SBError(E_TRUNCATED_DOWNLOAD, "Truncated/empty download", detail={"bytes": bytes_written}, url=url, retryable=True, severity="error")

            if expected_total is None:
                raise SBError(
                    E_TRUNCATED_DOWNLOAD,
                    "Missing size metadata to validate download",
                    detail={"bytes": bytes_written, "policy": "require_content_length_or_expected_size"},
                    url=url,
                    retryable=False,
                    severity="error",
                )

            if bytes_written != expected_total:
                if bytes_written > expected_total:
                    try:
                        partial.unlink()
                    except FileNotFoundError:
                        pass
                raise SBError(
                    E_TRUNCATED_DOWNLOAD,
                    "Download size mismatch",
                    detail={"bytes": bytes_written, "expected": expected_total},
                    url=url,
                    retryable=True,
                    severity="error",
                )

            try:
                os.replace(partial, dest_path)
            except OSError as e:
                raise SBError(E_ATOMIC_RENAME_FAILED, "Atomic rename failed", detail=str(e), url=url, path=str(dest_path), retryable=False, severity="fatal")

            st = dest_path.stat()
            mtime_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
            return DownloadResult(sha256=h.hexdigest(), size_bytes=st.st_size, mtime_utc=mtime_utc, skipped=False)

        except urllib.error.HTTPError as e:
            if e.code == 416 and resume and partial.exists():
                try:
                    partial.unlink()
                except FileNotFoundError:
                    pass
                if attempt < max_attempts:
                    time.sleep(_compute_backoff(attempt))
                    continue
            sb = _http_error_to_sberr(e, url)
            if sb.code == E_HTTP_429:
                ra = None
                try:
                    ra = int(e.headers.get("Retry-After") or "0")
                except Exception:
                    ra = None
                if ra and ra > 0:
                    time.sleep(min(60, ra))
                    continue
            if sb.retryable and attempt < max_attempts:
                time.sleep(_compute_backoff(attempt))
                continue
            raise sb

        except urllib.error.URLError as e:
            msg = str(e.reason) if hasattr(e, "reason") else str(e)
            is_timeout = "timed out" in msg.lower()
            sb = SBError(E_TIMEOUT if is_timeout else E_CONNECTION, "Network error", detail=msg, url=url, retryable=True, severity="error")
            if attempt < max_attempts:
                time.sleep(_compute_backoff(attempt))
                continue
            raise sb

        except SBError as e:
            if e.retryable and attempt < max_attempts:
                time.sleep(_compute_backoff(attempt))
                continue
            raise

    raise SBError(E_CONNECTION, "Download failed after retries", detail={"url": url}, url=url, retryable=False, severity="fatal")
