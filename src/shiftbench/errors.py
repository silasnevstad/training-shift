from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Literal

Severity = Literal["warn", "error", "fatal"]

# Resolution errors
E_SCOPE_INVALID = "E_SCOPE_INVALID"
E_REF_NOT_FOUND = "E_REF_NOT_FOUND"
E_ASSET_MISSING = "E_ASSET_MISSING"
E_AMBIGUOUS_MATCH = "E_AMBIGUOUS_MATCH"

# Network / HTTP errors
E_HTTP_404 = "E_HTTP_404"
E_HTTP_403 = "E_HTTP_403"
E_HTTP_429 = "E_HTTP_429"
E_TIMEOUT = "E_TIMEOUT"
E_CONNECTION = "E_CONNECTION"
E_HTTP_5XX = "E_HTTP_5XX"

# Integrity errors
E_CHECKSUM_MISMATCH = "E_CHECKSUM_MISMATCH"
E_TRUNCATED_DOWNLOAD = "E_TRUNCATED_DOWNLOAD"
E_JSON_PARSE = "E_JSON_PARSE"
E_SCHEMA_UNSUPPORTED = "E_SCHEMA_UNSUPPORTED"

# Filesystem errors
E_NO_SPACE = "E_NO_SPACE"
E_PERMISSION = "E_PERMISSION"
E_ATOMIC_RENAME_FAILED = "E_ATOMIC_RENAME_FAILED"
E_IO = "E_IO"
E_UNSAFE_DEST_PATH = "E_UNSAFE_DEST_PATH"

# Policy errors
E_FLOATING_REF_DISALLOWED = "E_FLOATING_REF_DISALLOWED"
E_TERMS_ACK_REQUIRED = "E_TERMS_ACK_REQUIRED"

@dataclass(frozen=True)
class SBError(Exception):
    code: str
    message: str
    detail: Any = None
    url: Optional[str] = None
    path: Optional[str] = None
    retryable: bool = False
    severity: Severity = "error"

    def to_manifest_record(self) -> Dict[str, Any]:
        rec: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }
        if self.url:
            rec["url"] = self.url
        if self.path:
            rec["path"] = self.path

        # Preserve required shape but keep taxonomy metadata available.
        if isinstance(rec.get("detail"), dict):
            rec["detail"].setdefault("retryable", self.retryable)
            rec["detail"].setdefault("severity", self.severity)
        else:
            rec["detail"] = {"detail": rec.get("detail"), "retryable": self.retryable, "severity": self.severity}
        return rec

def classify_os_error(exc: OSError) -> SBError:
    import errno
    if exc.errno == errno.ENOSPC:
        return SBError(E_NO_SPACE, "No space left on device", detail=str(exc), retryable=False, severity="fatal")
    if exc.errno in (errno.EACCES, errno.EPERM):
        return SBError(E_PERMISSION, "Permission error", detail=str(exc), retryable=False, severity="fatal")
    return SBError(E_IO, "Filesystem I/O error", detail=str(exc), retryable=False, severity="fatal")
