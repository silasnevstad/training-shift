from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timezone

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def stable_sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()

def scope_fingerprint(scope_obj: Any) -> str:
    b = canonical_json(scope_obj).encode("utf-8")
    return stable_sha256_hex(b)[:16]

def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, canonical_json(obj))

def sanitize_ref_for_path(ref: str) -> str:
    out = []
    for ch in ref.strip():
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    return s[:128] if len(s) > 128 else s

def try_git_commit(repo_root: Optional[Path] = None) -> Optional[str]:
    repo_root = repo_root or Path.cwd()
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if cp.returncode != 0:
            return None
        sha = cp.stdout.strip()
        return sha if sha else None
    except Exception:
        return None

def get_git_commit(repo_root: Optional[Path] = None) -> Optional[str]:
    return try_git_commit(repo_root)

def environment_summary(shiftbench_version: str) -> Dict[str, str]:
    return {
        "shiftbench_version": shiftbench_version,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "git_commit": get_git_commit(Path.cwd()) or "",
    }

def is_probably_commit_sha(ref: str) -> bool:
    r = ref.strip()
    if len(r) not in (7, 8, 9, 10, 40):
        return False
    try:
        int(r, 16)
        return True
    except ValueError:
        return False

def normalize_scope_obj(scope: Any) -> Any:
    if isinstance(scope, dict):
        return {k: normalize_scope_obj(scope[k]) for k in sorted(scope.keys())}
    if isinstance(scope, list):
        normed = [normalize_scope_obj(x) for x in scope]
        try:
            pairs = [(canonical_json(x), x) for x in normed]
            pairs.sort(key=lambda t: t[0])
            return [x for _, x in pairs]
        except Exception:
            return normed
    return scope
