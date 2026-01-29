"""shiftbench: deterministic dataset ingestion + provenance for training-shift.

Implements the ingestion/resolution/integrity execution spec for:
  - nflverse/nflverse-data (GitHub releases assets)
  - statsbomb/open-data (GitHub repo JSONs)

Entry point: `shiftbench` CLI.
"""
from __future__ import annotations

__all__ = ["__version__"]
__version__ = "0.1.0"
