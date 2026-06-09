"""Public one-shot bootstrap helpers.

These helpers reflect existing Spark tables into UMF, optionally profile the
data to derive GX expectations, and compile the full artifact tree in one call.

The native profiler enriches validation; it does not create UMF.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from tablespec.e2e.compile import compile_umfs
from tablespec.e2e.manifest import CompiledArtifacts
from tablespec.e2e.paths import umfs_from_tables

__all__ = ["bootstrap_from_tables"]

InferKeysMode = Literal["none", "candidates", "auto"]


def bootstrap_from_tables(
    spark: Any,
    table_names: str | Sequence[str],
    out_dir: str | Path,
    *,
    profile: bool = True,
    dialect: str = "duckdb",
    gold_targets: Sequence[str] | None = None,
    infer_keys: InferKeysMode = "none",
    key_promotion_min_score: float = 0.9,
    key_promotion_min_gap: float = 0.05,
) -> CompiledArtifacts:
    """Bootstrap one or more existing Spark tables into compiled artifacts."""
    tables = [table_names] if isinstance(table_names, str) else list(table_names)
    key_candidates: dict[str, list[dict[str, Any]]] = {}
    umfs, suites = umfs_from_tables(
        spark,
        tables,
        profile=profile,
        infer_key_candidates=infer_keys in {"candidates", "auto"},
        key_candidates_out=key_candidates,
    )
    return compile_umfs(
        umfs,
        out_dir,
        source="tables",
        profile_enriched=profile,
        dialect=dialect,
        gold_targets=list(gold_targets) if gold_targets is not None else None,
        suites=suites or None,
        infer_keys=infer_keys,
        key_candidates=key_candidates,
        key_promotion_min_score=key_promotion_min_score,
        key_promotion_min_gap=key_promotion_min_gap,
    )
