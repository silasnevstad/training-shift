from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import SBError, E_HTTP_404, E_FLOATING_REF_DISALLOWED, E_UNSAFE_DEST_PATH
from .util import (
    utc_now_iso,
    scope_fingerprint,
    sanitize_ref_for_path,
    environment_summary,
    normalize_scope_obj,
    atomic_write_json,
)
from .observability import StructuredLogger
from .http import stream_download
from .github import GitHubClient
from .schema import infer_schema_for_file, build_drift_report
from .sources.nflverse import NFLVerseResolver
from .sources.statsbomb_open_data import StatsBombOpenDataResolver


@dataclass
class IngestConfig:
    source: str
    ref: str
    scope: Dict[str, Any]
    out_dir: Path = Path("data/raw")
    cache_dir: Path = Path("data/.cache/shiftbench")
    max_parallel: int = 4
    dry_run: bool = False
    allow_missing: bool = False
    allow_floating: bool = False
    require_360: bool = False
    github_api_base: str = "https://api.github.com"
    github_raw_base: str = "https://raw.githubusercontent.com"


def _terms_and_attribution(source: str) -> Dict[str, Any]:
    if source == "statsbomb-open-data":
        return {
            "requirements": [
                "If you publish/ship results, attribute StatsBomb as the data source and use their logo per their open-data README.",
            ],
            "sources": [
                {"name": "StatsBomb Open Data", "url": "https://github.com/statsbomb/open-data",
                 "notes": "Attribution required."},
            ],
        }
    if source == "nflverse":
        return {
            "requirements": [
                "Attribute nflverse and underlying dataset authors as applicable.",
            ],
            "sources": [
                {"name": "nflverse-data", "url": "https://github.com/nflverse/nflverse-data",
                 "notes": "Data stored in GitHub releases assets."},
            ],
        }
    return {"requirements": [], "sources": []}


def _hash_file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_download_path(downloads_dir: Path, dest_rel: str) -> Path:
    if not dest_rel:
        raise SBError(E_UNSAFE_DEST_PATH, "Empty dest_path rejected", detail={"dest_path": dest_rel}, retryable=False,
                      severity="fatal")
    rel_path = Path(dest_rel)
    if rel_path.is_absolute():
        raise SBError(E_UNSAFE_DEST_PATH, "Absolute dest_path rejected", detail={"dest_path": dest_rel},
                      retryable=False, severity="fatal")
    base = downloads_dir.resolve()
    dest = (downloads_dir / rel_path).resolve()
    try:
        dest.relative_to(base)
    except ValueError:
        raise SBError(E_UNSAFE_DEST_PATH, "dest_path escapes downloads_dir", detail={"dest_path": dest_rel},
                      retryable=False, severity="fatal")
    return dest


def _build_manifest(
        *,
        run_id: str,
        started_at: str,
        finished_at: str,
        source: str,
        source_ref: str,
        requested_scope: Dict[str, Any],
        resolved_plan: List[Dict[str, Any]],
        status: str,
        downloaded_files: int,
        skipped_files: int,
        failed_files: int,
        errors: List[Dict[str, Any]],
        env: Dict[str, Any],
        terms: Dict[str, Any],
        config: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "source": source,
        "source_ref": source_ref,
        "requested_scope": requested_scope,
        "config": config,
        "resolved_plan": resolved_plan,
        "results": {
            "status": status,
            "downloaded_files": int(downloaded_files),
            "skipped_files": int(skipped_files),
            "failed_files": int(failed_files),
            "errors": errors,
        },
        "environment": env,
        "terms_and_attribution": terms,
    }


def ingest(cfg: IngestConfig) -> Path:
    run_id = str(uuid.uuid4())
    started = utc_now_iso()

    norm_scope = normalize_scope_obj(cfg.scope)
    scope_fp = scope_fingerprint(norm_scope)

    source_ref_for_path = sanitize_ref_for_path(cfg.ref)
    ingest_dir = Path(cfg.out_dir) / cfg.source / source_ref_for_path / scope_fp
    downloads_dir = ingest_dir / "downloads"
    logs_dir = ingest_dir / "logs"

    manifest_path = ingest_dir / "manifest.json"
    checksums_path = ingest_dir / "checksums.json"
    schema_path = ingest_dir / "schema.json"
    drift_path = ingest_dir / "drift_report.json"
    log_path = logs_dir / "ingest.log"

    downloads_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = StructuredLogger(log_path, base_fields={
        "run_id": run_id,
        "source": cfg.source,
        "source_ref": cfg.ref,
        "scope_fingerprint": scope_fp,
    })

    gh_cache = Path(cfg.cache_dir) / "meta" / "github"
    gh = GitHubClient(api_base=cfg.github_api_base, cache_dir=gh_cache)

    errors: List[Dict[str, Any]] = []
    resolved_plan: List[Dict[str, Any]] = []
    downloaded = 0
    skipped = 0
    failed = 0

    source_ref_resolved = cfg.ref

    logger.event("resolve", "start_resolve", requested_scope=norm_scope)

    # Resolve plan
    if cfg.source == "nflverse":
        resolver = NFLVerseResolver(gh)
        tag, items = resolver.resolve(cfg.ref, norm_scope, allow_missing=cfg.allow_missing)
        source_ref_resolved = tag
        source_ref_for_path = sanitize_ref_for_path(source_ref_resolved)
        ingest_dir = Path(cfg.out_dir) / cfg.source / source_ref_for_path / scope_fp
        downloads_dir = ingest_dir / "downloads"
        logs_dir = ingest_dir / "logs"
        manifest_path = ingest_dir / "manifest.json"
        checksums_path = ingest_dir / "checksums.json"
        schema_path = ingest_dir / "schema.json"
        drift_path = ingest_dir / "drift_report.json"
        log_path = logs_dir / "ingest.log"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        logger = StructuredLogger(log_path, base_fields={
            "run_id": run_id,
            "source": cfg.source,
            "source_ref": source_ref_resolved,
            "scope_fingerprint": scope_fp,
        })
        for it in items:
            resolved_plan.append({
                "logical_name": it.logical_name,
                "url": it.url,
                "dest_path": it.dest_path,
                "expected_type": it.expected_type,
                "expected_size_bytes": it.expected_size_bytes,
                "sha256": it.sha256,
                "group": it.group,
                "season": it.season,
            })

    elif cfg.source == "statsbomb-open-data":
        resolver = StatsBombOpenDataResolver(gh, raw_base=cfg.github_raw_base)
        commit_sha, items = resolver.resolve(cfg.ref, norm_scope, allow_floating=cfg.allow_floating)
        source_ref_resolved = commit_sha
        source_ref_for_path = sanitize_ref_for_path(source_ref_resolved)
        ingest_dir = Path(cfg.out_dir) / cfg.source / source_ref_for_path / scope_fp
        downloads_dir = ingest_dir / "downloads"
        logs_dir = ingest_dir / "logs"
        manifest_path = ingest_dir / "manifest.json"
        checksums_path = ingest_dir / "checksums.json"
        schema_path = ingest_dir / "schema.json"
        drift_path = ingest_dir / "drift_report.json"
        log_path = logs_dir / "ingest.log"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        logger = StructuredLogger(log_path, base_fields={
            "run_id": run_id,
            "source": cfg.source,
            "source_ref": source_ref_resolved,
            "scope_fingerprint": scope_fp,
        })
        for it in items:
            resolved_plan.append({
                "logical_name": it.logical_name,
                "url": it.url,
                "dest_path": it.dest_path,
                "expected_type": it.expected_type,
                "expected_size_bytes": it.expected_size_bytes,
                "sha256": it.sha256,
                "group": it.group,
                "optional": it.optional,
            })
    else:
        raise SBError("E_SCOPE_INVALID", "Unknown source", detail={"source": cfg.source}, retryable=False,
                      severity="fatal")

    logger.event("resolve", "resolve_ok", planned_files=len([p for p in resolved_plan if p.get("url")]))

    for p in resolved_plan:
        dest_rel = p.get("dest_path")
        if not dest_rel:
            continue
        _safe_download_path(downloads_dir, str(dest_rel))

    if cfg.dry_run:
        finished = utc_now_iso()
        manifest = _build_manifest(
            run_id=run_id,
            started_at=started,
            finished_at=finished,
            source=cfg.source,
            source_ref=source_ref_resolved,
            requested_scope=norm_scope,
            resolved_plan=resolved_plan,
            config={"require_360": cfg.require_360},
            status="success",
            downloaded_files=0,
            skipped_files=0,
            failed_files=0,
            errors=[],
            env=environment_summary("0.1.0"),
            terms=_terms_and_attribution(cfg.source),
        )
        atomic_write_json(manifest_path, manifest)
        atomic_write_json(checksums_path, {})
        atomic_write_json(schema_path, [])
        atomic_write_json(drift_path, {"groups": {}})
        logger.event("finalize", "dry_run_complete", manifest_path=str(manifest_path))
        return ingest_dir

    # Download phase
    checksums: Dict[str, Any] = {}
    if checksums_path.exists():
        try:
            checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
        except Exception:
            checksums = {}

    def _download_one(p: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        url = p.get("url") or ""
        if not url:
            return ("", None, None)
        dest_rel = str(p["dest_path"])
        try:
            dest = _safe_download_path(downloads_dir, dest_rel)
        except SBError as e:
            return (dest_rel, None, e.to_manifest_record())

        rec = checksums.get(dest_rel)
        if dest.exists() and rec and rec.get("sha256"):
            return (dest_rel, {"skipped": True, **rec}, None)

        try:
            res = stream_download(url, dest, expected_size_bytes=p.get("expected_size_bytes"))
            return (dest_rel,
                    {"sha256": res.sha256, "size_bytes": res.size_bytes, "mtime_utc": res.mtime_utc, "skipped": False},
                    None)
        except SBError as e:
            optional = bool(p.get("optional", False))
            # Optional policy: only HTTP 404s are non-gating for optional assets.
            if p.get("group") == "three-sixty" and cfg.require_360:
                optional = False
            if optional and e.code == E_HTTP_404:
                warn = e.to_manifest_record()
                warn["detail"]["optional"] = True
                return dest_rel, None, warn
            return dest_rel, None, e.to_manifest_record()

    def _handle_download_result(logical, dest_rel, checksum_rec, err_rec):
        nonlocal downloaded, skipped, failed
        if err_rec:
            if err_rec.get("detail", {}).get("optional"):
                errors.append(err_rec)
                logger.warn("download", "optional_missing", logical_name=logical, error=err_rec)
            else:
                errors.append(err_rec)
                failed += 1
                logger.error("download", "download_failed", logical_name=logical, error=err_rec)
        if checksum_rec:
            if checksum_rec.get("skipped"):
                skipped += 1
            else:
                downloaded += 1
            checksums[dest_rel] = {"sha256": checksum_rec["sha256"], "size_bytes": checksum_rec["size_bytes"],
                                   "mtime_utc": checksum_rec["mtime_utc"]}
            logger.event("download", "download_ok" if not checksum_rec.get("skipped") else "download_skipped",
                         logical_name=logical, dest_path=dest_rel)

    planned = [p for p in resolved_plan if p.get("url")]
    logger.event("download", "download_start", planned=len(planned))

    with ThreadPoolExecutor(max_workers=max(1, int(cfg.max_parallel))) as ex:
        futs = {ex.submit(_download_one, p): p for p in planned}
        for fut in as_completed(futs):
            p = futs[fut]
            logical = p.get("logical_name")
            dest_rel, checksum_rec, err_rec = fut.result()
            _handle_download_result(logical, dest_rel, checksum_rec, err_rec)

    # StatsBomb expansion: pairs -> matches -> match artifacts
    if cfg.source == "statsbomb-open-data":
        resolver = StatsBombOpenDataResolver(gh, raw_base=cfg.github_raw_base)
        comp_path = downloads_dir / f"statsbomb-open-data/{source_ref_resolved}/competitions.json"
        try:
            pairs = resolver.expand_pairs_from_competitions(comp_path, norm_scope)
            match_files = resolver.plan_matches_files(source_ref_resolved, pairs)
            match_plan = []
            for it in match_files:
                match_plan.append({
                    "logical_name": it.logical_name,
                    "url": it.url,
                    "dest_path": it.dest_path,
                    "expected_type": it.expected_type,
                    "expected_size_bytes": it.expected_size_bytes,
                    "sha256": it.sha256,
                    "group": it.group,
                    "optional": it.optional,
                })
            # Download matches files
            with ThreadPoolExecutor(max_workers=max(1, int(cfg.max_parallel))) as ex:
                futs = {ex.submit(_download_one, p): p for p in match_plan}
                for fut in as_completed(futs):
                    p = futs[fut]
                    logical = p.get("logical_name")
                    dest_rel, checksum_rec, err_rec = fut.result()
                    _handle_download_result(logical, dest_rel, checksum_rec, err_rec)
            resolved_plan.extend(match_plan)

            # Extract match ids and download artifacts
            match_ids = []
            for p in match_plan:
                dest = _safe_download_path(downloads_dir, str(p["dest_path"]))
                if dest.exists():
                    match_ids.extend(resolver.extract_match_ids(dest))
            match_ids = sorted(set(match_ids))
            artifacts = resolver.plan_match_artifacts(source_ref_resolved, match_ids)
            art_plan = []
            for it in artifacts:
                art_plan.append({
                    "logical_name": it.logical_name,
                    "url": it.url,
                    "dest_path": it.dest_path,
                    "expected_type": it.expected_type,
                    "expected_size_bytes": it.expected_size_bytes,
                    "sha256": it.sha256,
                    "group": it.group,
                    "optional": it.optional,
                })
            with ThreadPoolExecutor(max_workers=max(1, int(cfg.max_parallel))) as ex:
                futs = {ex.submit(_download_one, p): p for p in art_plan}
                for fut in as_completed(futs):
                    p = futs[fut]
                    logical = p.get("logical_name")
                    dest_rel, checksum_rec, err_rec = fut.result()
                    _handle_download_result(logical, dest_rel, checksum_rec, err_rec)
            resolved_plan.extend(art_plan)
        except SBError as e:
            errors.append(e.to_manifest_record())
            failed += 1
            logger.error("resolve", "expansion_failed", error=e.to_manifest_record())
        except Exception as e:
            sb = SBError("E_EXPANSION_FAILED", "StatsBomb expansion failed", detail=str(e), retryable=False,
                         severity="fatal")
            errors.append(sb.to_manifest_record())
            failed += 1
            logger.error("resolve", "expansion_failed", error=sb.to_manifest_record())

    # Persist checksums
    atomic_write_json(checksums_path, checksums)

    status = "success"
    if failed > 0 and downloaded == 0:
        status = "failed"
    elif failed > 0 or any(e.get("detail", {}).get("optional") for e in errors):
        status = "partial"

    # Schema phase
    schema_entries: List[Dict[str, Any]] = []
    for p in resolved_plan:
        dest_rel = p.get("dest_path")
        if not dest_rel:
            continue
        dest = _safe_download_path(downloads_dir, str(dest_rel))
        if not dest.exists():
            continue
        try:
            sch = infer_schema_for_file(dest)
            sch["logical_name"] = p.get("logical_name")
            sch["group"] = p.get("group")
            schema_entries.append(sch)
        except SBError as e:
            errors.append(e.to_manifest_record())
            logger.warn("schema", "schema_failed", path=str(dest), error=e.to_manifest_record())

    atomic_write_json(schema_path, schema_entries)
    atomic_write_json(drift_path, build_drift_report(schema_entries, group_key="group"))

    finished = utc_now_iso()
    manifest = _build_manifest(
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        source=cfg.source,
        source_ref=source_ref_resolved,
        requested_scope=norm_scope,
        config={"require_360": cfg.require_360},
        resolved_plan=resolved_plan,
        status=status,
        downloaded_files=downloaded,
        skipped_files=skipped,
        failed_files=failed,
        errors=errors,
        env=environment_summary("0.1.0"),
        terms=_terms_and_attribution(cfg.source),
    )
    atomic_write_json(manifest_path, manifest)
    logger.event("finalize", "ingest_complete", status=status, downloaded=downloaded, skipped=skipped, failed=failed)
    return ingest_dir


def verify_ingestion_integrity(
        ingest_dir: Path,
        *,
        require_360: bool = False,
        resolved_plan: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    checksums_path = ingest_dir / "checksums.json"
    downloads_dir = ingest_dir / "downloads"
    if not checksums_path.exists():
        errors.append({"code": "E_CHECKSUMS_MISSING", "message": "checksums.json missing", "detail": None})
        return False, errors
    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
    ok = True
    for dest_rel, rec in checksums.items():
        try:
            dest = _safe_download_path(downloads_dir, str(dest_rel))
        except SBError as e:
            ok = False
            errors.append(e.to_manifest_record())
            continue
        if not dest.exists():
            ok = False
            errors.append(
                {"code": "E_FILE_MISSING", "message": "Downloaded file missing", "detail": {"dest_path": dest_rel}})
            continue
        sha = _hash_file_sha256(dest)
        if sha != rec.get("sha256"):
            ok = False
            errors.append({"code": "E_CHECKSUM_MISMATCH", "message": "Checksum mismatch",
                           "detail": {"dest_path": dest_rel, "expected": rec.get("sha256"), "actual": sha}})
    if require_360:
        for item in resolved_plan or []:
            if item.get("group") != "three-sixty":
                continue
            dest_rel = str(item.get("dest_path") or "")
            if not dest_rel:
                continue
            try:
                dest = _safe_download_path(downloads_dir, dest_rel)
            except SBError as e:
                ok = False
                errors.append(e.to_manifest_record())
                continue
            if not dest.exists():
                ok = False
                errors.append({
                    "code": "E_REQUIRED_ASSET_MISSING",
                    "message": "Required three-sixty asset missing",
                    "detail": {"dest_path": dest_rel},
                })
                continue
            if dest_rel not in checksums:
                ok = False
                errors.append({
                    "code": "E_CHECKSUM_RECORD_MISSING",
                    "message": "Checksum record missing for required asset",
                    "detail": {"dest_path": dest_rel},
                })
    return ok, errors
