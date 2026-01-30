from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import click

from .ingest import IngestConfig, ingest, verify_ingestion_integrity
from .errors import SBError

def _parse_scope(scope_json: Optional[str], scope_file: Optional[str]) -> Dict[str, Any]:
    if scope_json:
        return json.loads(scope_json)
    if scope_file:
        return json.loads(Path(scope_file).read_text(encoding="utf-8"))
    raise click.UsageError("Provide --scope JSON or --scope-file.")

@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """shiftbench: deterministic ingestion + provenance."""
    pass

@cli.command("ingest")
@click.option("--source", type=click.Choice(["nflverse", "statsbomb-open-data"], case_sensitive=False), required=True)
@click.option("--ref", required=True)
@click.option("--scope", default=None, help="Scope JSON string.")
@click.option("--scope-file", default=None, help="Scope JSON file path.")
@click.option("--out", "out_dir", default="data/raw", type=click.Path(), show_default=True)
@click.option("--cache", "cache_dir", default="data/.cache/shiftbench", type=click.Path(), show_default=True)
@click.option("--max-parallel", default=4, type=int, show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--allow-missing", is_flag=True)
@click.option("--allow-floating", is_flag=True)
@click.option("--require-360", is_flag=True)
def ingest_cmd(source: str, ref: str, scope: Optional[str], scope_file: Optional[str], out_dir: str, cache_dir: str, max_parallel: int, dry_run: bool, allow_missing: bool, allow_floating: bool, require_360: bool) -> None:
    try:
        scope_obj = _parse_scope(scope, scope_file)
    except json.JSONDecodeError as e:
        raise click.UsageError(f"Invalid scope JSON: {e}")

    cfg = IngestConfig(
        source=source.lower(),
        ref=ref,
        scope=scope_obj,
        out_dir=Path(out_dir),
        cache_dir=Path(cache_dir),
        max_parallel=max_parallel,
        dry_run=dry_run,
        allow_missing=allow_missing,
        allow_floating=allow_floating,
        require_360=require_360,
    )
    try:
        ingest_dir = ingest(cfg)
    except SBError as e:
        click.echo(json.dumps(e.to_manifest_record(), indent=2), err=True)
        sys.exit(2)
    click.echo(str(ingest_dir))

@cli.command("build-dataset")
@click.option("--ingest-dir", required=True, type=click.Path(exists=True))
@click.option("--allow-floating", is_flag=True)
def build_dataset_cmd(ingest_dir: str, allow_floating: bool) -> None:
    p = Path(ingest_dir)
    manifest_path = p / "manifest.json"
    if not manifest_path.exists():
        click.echo("manifest.json missing; run shiftbench ingest first.", err=True)
        sys.exit(2)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest.get("source")
    source_ref = manifest.get("source_ref")
    if source == "statsbomb-open-data":
        if not (isinstance(source_ref, str) and len(source_ref) == 40):
            if not allow_floating:
                click.echo("Floating ref disallowed: statsbomb-open-data source_ref is not a 40-char commit SHA.", err=True)
                sys.exit(2)

    config = manifest.get("config") or {}
    require_360 = bool(config.get("require_360", False))
    ok, errs = verify_ingestion_integrity(
        p,
        require_360=require_360,
        resolved_plan=manifest.get("resolved_plan") or [],
    )
    if not ok:
        click.echo(json.dumps({"integrity": "failed", "errors": errs}, indent=2), err=True)
        sys.exit(2)

    click.echo("OK: manifest present, checksums verified, ref pinned (or explicitly allowed).")
