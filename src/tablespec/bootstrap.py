"""Public one-shot bootstrap helpers.

Path A — existing Spark tables → reflect (+ optional profile) → compile.
Path B — authored UMF specs → load → compile.

Both return a :class:`~tablespec.e2e.manifest.CompiledArtifacts` tree suitable
for review and for ``run_backbone``. The native profiler enriches validation; it
does not create UMF.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from tablespec.e2e.compile import compile_umfs
from tablespec.e2e.manifest import CompiledArtifacts
from tablespec.e2e.paths import umfs_from_specs, umfs_from_tables

__all__ = ["bootstrap_from_tables", "bootstrap_from_specs"]

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
    """Path A: bootstrap one or more existing Spark tables into compiled artifacts."""
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


def bootstrap_from_specs(
    spec_paths: str | Path | Sequence[str | Path],
    out_dir: str | Path,
    *,
    dialect: str = "duckdb",
    gold_targets: Sequence[str] | None = None,
) -> CompiledArtifacts:
    """Path B: bootstrap authored UMF specs into compiled artifacts (no Spark).

    Accepts split table directories, ``*.umf.yaml``, or JSON interchange paths —
    anything :func:`~tablespec.e2e.paths.umfs_from_specs` loads.
    """
    if isinstance(spec_paths, (str, Path)):
        paths: list[str | Path] = [spec_paths]
    else:
        paths = list(spec_paths)
    umfs = umfs_from_specs(paths)
    return compile_umfs(
        umfs,
        out_dir,
        source="specs",
        profile_enriched=False,
        dialect=dialect,
        gold_targets=list(gold_targets) if gold_targets is not None else None,
    )

