from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .util import utc_now_iso, canonical_json

class StructuredLogger:
    def __init__(self, log_path: Path, base_fields: Dict[str, Any]):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.base_fields = dict(base_fields)

    def _write_line(self, obj: Dict[str, Any]) -> None:
        line = canonical_json(obj)
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

    def event(self, phase: str, msg: str, **fields: Any) -> None:
        payload = dict(self.base_fields)
        payload.update({"ts_utc": utc_now_iso(), "phase": phase, "msg": msg})
        payload.update(fields)
        self._write_line(payload)

    def warn(self, phase: str, msg: str, **fields: Any) -> None:
        self.event(phase, msg, level="warn", **fields)

    def error(self, phase: str, msg: str, **fields: Any) -> None:
        self.event(phase, msg, level="error", **fields)
