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
) -> DownloadResult:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    partial = dest_path.with_suffix(dest_path.suffix + ".partial")

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
                if start_at > 0 and resp.status == 200:
                    start_at = 0
                    h = hashlib.sha256()
                    try:
                        partial.unlink()
                    except FileNotFoundError:
                        pass

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

            if bytes_written < min_size_bytes:
                raise SBError(E_TRUNCATED_DOWNLOAD, "Truncated/empty download", detail={"bytes": bytes_written}, url=url, retryable=True, severity="error")

            try:
                os.replace(partial, dest_path)
            except OSError as e:
                raise SBError(E_ATOMIC_RENAME_FAILED, "Atomic rename failed", detail=str(e), url=url, path=str(dest_path), retryable=False, severity="fatal")

            st = dest_path.stat()
            mtime_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
            return DownloadResult(sha256=h.hexdigest(), size_bytes=st.st_size, mtime_utc=mtime_utc, skipped=False)

        except urllib.error.HTTPError as e:
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
