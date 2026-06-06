"""The runtime BACKBONE: execute the COMPILED artifacts (never the UMF).

Given a :class:`~tablespec.e2e.manifest.CompiledArtifacts` (from the compile
orchestrator) and raw input batches, run the staged runtime exactly as production
would, consuming the persisted artifacts:

  1. INGEST raw -> ROW: execute the COMPILED split ingest SQL. The raw landing
     table is all-STRING + ``_source_file`` + ``_load_ts`` -- matching the
     conformance oracle loader at ``tests/conformance/engines.py:527`` (reused as a
     FACADE; do NOT reimplement the raw-load schema here).
  2. VALIDATE RAW via :meth:`GXSuiteExecutor.execute_staged(raw_df, ingested_df,
     expectations)` using the COMPILED suite JSON -- NOT ``TableValidator``.
     Connect DataFrames auto-route to the native path inside the executor.
  3. INGEST ROW -> INGESTED: the compiled cast + MERGE/INSERT transform statement.
  4. VALIDATE INGESTED (same staged executor; the ingested-stage expectations).
  5. TRANSFORMS:
       * dbt PARSE always (offline manifest, no warehouse).
       * dbt COMPILE/RUN only on duckdb / local-spark (Databricks dbt compile needs
         a live warehouse -> parse-only there).
       * execute the gold SQL plan where supported.
       * LDP = structure golden + local cast-body parity (single-batch only);
         APPLY CHANGES execution ONLY on real Databricks.

Tiering + canonicalization REUSE the conformance facades in
``tests/conformance/engines.py`` (row / compile / structure / opt-in e2e) and the
``tests/ingest_parity/canonical.to_json`` byte-parity canonicalizer. This module
does NOT build a parallel harness -- it wires the compiled artifacts INTO those
engines. The real-serverless leg is gated by
:func:`engines.databricks_e2e_availability` (``DATABRICKS_HOST`` opt-in); local
success NEVER depends on a remote workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tablespec.e2e.manifest import CompiledArtifacts


@dataclass(frozen=True)
class StageOutcome:
    """Result of one backbone stage (ingest / validate / transform leg)."""

    name: str
    ok: bool
    detail: str = ""
    canonical: str | None = None


@dataclass(frozen=True)
class BackboneResult:
    """Aggregate of every backbone stage that ran for a compile."""

    stages: list[StageOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff every stage that ran succeeded."""
        raise NotImplementedError


def run_backbone(
    artifacts: CompiledArtifacts,
    *,
    spark: Any,
    raw_batches: dict[str, list[Path]],
    run_transforms: bool = True,
) -> BackboneResult:
    """Execute the compiled artifacts end to end against *raw_batches*.

    Args:
        artifacts: the compile manifest to consume (paths already absolute).
        spark: active Spark (classic or Connect) session for ingest + validation.
        raw_batches: per-table ordered raw CSV batch paths to ingest.
        run_transforms: also run the transform legs (stage 5). Disabled in a
            pure ingest+validate smoke run.

    Returns:
        A :class:`BackboneResult` enumerating each stage outcome.
    """
    raise NotImplementedError


# --- stage helpers (each consumes a COMPILED artifact) ------------------------


def _ingest_to_row(spark: Any, artifacts: CompiledArtifacts, table: str, batches: list[Path]):
    """Stage 1: execute compiled ingest CREATE + transform; return (raw_df, ingested_df).

    Reuses the conformance oracle raw-load schema (all-STRING + ``_source_file`` +
    ``_load_ts``) so the raw landing frame is byte-identical to the corpus golden.
    """
    raise NotImplementedError


def _validate_stage(spark: Any, raw_df: Any, ingested_df: Any, suite_path: Path) -> StageOutcome:
    """Stages 2 & 4: run ``GXSuiteExecutor.execute_staged`` with the compiled suite.

    Loads the compiled expectation list from *suite_path* and classifies/executes
    raw-stage vs ingested-stage expectations inside the executor.
    """
    raise NotImplementedError


def _run_dbt_transforms(artifacts: CompiledArtifacts, *, backend: str) -> list[StageOutcome]:
    """Stage 5 (dbt): parse always; compile/run on duckdb/local-spark only."""
    raise NotImplementedError


def _run_gold_plan(spark: Any, artifacts: CompiledArtifacts) -> list[StageOutcome]:
    """Stage 5 (gold): execute the compiled single-target gold SQL plan(s)."""
    raise NotImplementedError


def _run_ldp(artifacts: CompiledArtifacts) -> list[StageOutcome]:
    """Stage 5 (LDP): structure golden + local cast-body parity (single batch)."""
    raise NotImplementedError
