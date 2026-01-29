from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .util import canonical_json, stable_sha256_hex
from .errors import SBError, E_JSON_PARSE, E_SCHEMA_UNSUPPORTED

def schema_fingerprint(columns: List[str], dtypes: Dict[str, str]) -> str:
    payload = {"columns": columns, "dtypes": dict(sorted(dtypes.items(), key=lambda kv: kv[0]))}
    return stable_sha256_hex(canonical_json(payload).encode("utf-8"))

def _bounded_numeric_stats(series: pd.Series) -> Dict[str, Any]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) == 0:
        return {}
    return {
        "min": float(s.min()),
        "max": float(s.max()),
        "mean": float(s.mean()),
        "std": float(s.std(ddof=0)) if len(s) > 1 else 0.0,
    }

def _bounded_topk(series: pd.Series, k: int = 10) -> List[Tuple[Any, int]]:
    vc = series.value_counts(dropna=True)
    out: List[Tuple[Any, int]] = []
    for i, (key, cnt) in enumerate(vc.items()):
        if i >= k:
            break
        if isinstance(key, float) and math.isnan(key):
            continue
        out.append((key, int(cnt)))
    return out

def infer_schema_for_dataframe(df: pd.DataFrame, *, table_name: str, full_row_count: Optional[int]) -> Dict[str, Any]:
    n_rows = int(full_row_count) if full_row_count is not None else int(len(df))
    columns = [str(c) for c in df.columns.tolist()]
    dtypes: Dict[str, str] = {}
    null_fraction: Dict[str, float] = {}
    basic_stats: Dict[str, Any] = {}

    for c in columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s):
            dt = "bool"
        elif pd.api.types.is_integer_dtype(s):
            dt = "int"
        elif pd.api.types.is_float_dtype(s):
            dt = "float"
        elif pd.api.types.is_string_dtype(s):
            dt = "string"
        else:
            dt = "object"
        dtypes[c] = dt
        null_fraction[c] = float(s.isna().mean()) if len(s) else 0.0

        if dt in ("int", "float"):
            st = _bounded_numeric_stats(s)
            if st:
                basic_stats[c] = st
        else:
            top = _bounded_topk(s.astype(str), k=10) if len(s) else []
            if top:
                basic_stats[c] = {"top_values": top}

    fp = schema_fingerprint(columns, dtypes)
    return {
        "table_name": table_name,
        "n_rows": n_rows,
        "columns": columns,
        "dtypes": dtypes,
        "null_fraction": null_fraction,
        "basic_stats": basic_stats,
        "schema_fingerprint": fp,
    }

def infer_schema_for_csv(path: Path, *, max_rows: int = 200_000, chunk_rows: int = 50_000) -> Dict[str, Any]:
    rows = 0
    chunks = []
    for chunk in pd.read_csv(path, chunksize=chunk_rows):
        chunks.append(chunk)
        rows += len(chunk)
        if rows >= max_rows:
            break
    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    return infer_schema_for_dataframe(df, table_name=path.name, full_row_count=None)

def infer_schema_for_json(path: Path, *, max_rows: int = 200_000) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SBError(E_JSON_PARSE, "JSON parse failed", detail=str(e), path=str(path), retryable=False, severity="fatal")

    if isinstance(data, dict):
        df = pd.json_normalize([data])
        full = 1
    elif isinstance(data, list):
        df = pd.json_normalize(data[:max_rows])
        full = len(data)
    else:
        df = pd.DataFrame()
        full = None
    return infer_schema_for_dataframe(df, table_name=path.name, full_row_count=full)

def infer_schema_for_parquet(path: Path) -> Dict[str, Any]:
    try:
        import pyarrow.parquet as pq  # type: ignore
        table = pq.read_table(path)
        df = table.to_pandas()
        return infer_schema_for_dataframe(df, table_name=path.name, full_row_count=len(df))
    except Exception as e:
        raise SBError(E_SCHEMA_UNSUPPORTED, "Parquet schema unsupported (install pyarrow to enable)", detail=str(e), path=str(path), retryable=False, severity="warn")

def infer_schema_for_file(path: Path) -> Dict[str, Any]:
    suf = path.suffix.lower()
    if suf == ".csv":
        return infer_schema_for_csv(path)
    if suf == ".json":
        return infer_schema_for_json(path)
    if suf == ".parquet":
        return infer_schema_for_parquet(path)
    return {
        "table_name": path.name,
        "n_rows": 0,
        "columns": [],
        "dtypes": {},
        "null_fraction": {},
        "basic_stats": {},
        "schema_fingerprint": schema_fingerprint([], {}),
        "notes": f"unsupported extension: {suf}",
    }

def build_drift_report(schema_entries: List[Dict[str, Any]], *, group_key: str = "group") -> Dict[str, Any]:
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for e in schema_entries:
        g = str(e.get(group_key, "default"))
        by_group.setdefault(g, []).append(e)

    report: Dict[str, Any] = {"groups": {}}
    for g, entries in sorted(by_group.items(), key=lambda kv: kv[0]):
        fps: Dict[str, int] = {}
        for e in entries:
            fp = str(e.get("schema_fingerprint", ""))
            fps[fp] = fps.get(fp, 0) + 1

        baseline = entries[0]
        base_cols = set(baseline.get("columns", []))
        diffs = []
        for e in entries[1:]:
            cols = set(e.get("columns", []))
            added = sorted(list(cols - base_cols))
            removed = sorted(list(base_cols - cols))
            if added or removed:
                diffs.append({
                    "from": baseline.get("table_name"),
                    "to": e.get("table_name"),
                    "added_columns": added,
                    "removed_columns": removed,
                })

        report["groups"][g] = {
            "n_tables": len(entries),
            "fingerprint_histogram": fps,
            "column_diffs_against_first": diffs,
        }
    return report
