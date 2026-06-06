"""The COMPILE ORCHESTRATOR: UMF set -> persisted runtime artifacts.

There is NO single tablespec command that compiles a UMF into every runtime
artifact (the CLI ``generate`` only emits sql/pyspark/json/ingest). This module is
the explicit orchestrator: it calls each COMPILE SEAM and PERSISTS its output
under the pinned layout in :mod:`tablespec.e2e.manifest`, returning a
:class:`~tablespec.e2e.manifest.CompiledArtifacts` manifest the runtime BACKBONE
consumes.

Compile seams driven here (one persisted artifact each, per the corrected plan):

  * :func:`tablespec.schemas.ingest_generator.generate_ingest_sql`
        -> ``ingest/<t>.ingest.sql``  (raw DDL + typed DDL + transform)
  * :func:`tablespec.schemas.generators.generate_sql_ddl`
        -> ``schemas/<t>.ddl.sql``
  * :func:`tablespec.schemas.generators.generate_pyspark_schema`
        -> ``schemas/<t>.schema.py``
  * :func:`tablespec.schemas.generators.generate_json_schema`
        -> ``schemas/<t>.schema.json``
  * :func:`tablespec.gx_baseline.BaselineExpectationGenerator.generate_baseline_expectations`
        -> ``validation/<t>.suite.json``  (the COMPILED validation suite; raw +
           ingested expectations co-mingled, staged at execute time)
  * :func:`tablespec.dbt.single_table.generate_dbt_project`
        -> ``dbt_ingest/<t>/``  (single-table ingest project)
  * :func:`tablespec.dbt.project.generate_dbt_dag_project`
        -> ``dbt_gold/``  (multi-table GOLD dbt DAG project)
  * :func:`tablespec.ldp.project.generate_ldp_project`
        -> ``ldp/``
  * :func:`tablespec.schemas.sql_generator.generate_sql_plan`
        -> ``gold_plan/<target>.plan.sql``  (SINGLE-target gold plan; NOT the dag
           project -- the two are kept distinct on purpose)

Input is always a list of :class:`~tablespec.models.umf.UMF` models, regardless of
whether they came from Path A (inferred) or Path B (loaded). The two entry points
(:mod:`tablespec.e2e.paths`) produce that list; compile is path-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tablespec.models.umf import UMF

    from tablespec.e2e.manifest import CompiledArtifacts


def compile_umfs(
    umfs: list[UMF],
    out_dir: str | Path,
    *,
    source: str,
    profile_enriched: bool = False,
    dialect: str = "duckdb",
    gold_targets: list[str] | None = None,
    suites: dict[str, list[dict]] | None = None,
) -> CompiledArtifacts:
    """Compile *umfs* into persisted runtime artifacts under *out_dir*.

    Args:
        umfs: the table set to compile (already loaded/inferred into UMF models).
        out_dir: compile output root; the pinned layout is created beneath it.
        source: ``"tables"`` (Path A) or ``"specs"`` (Path B) -- recorded on the
            manifest for provenance, does not change the compile.
        profile_enriched: recorded on the manifest; True iff *suites* carry
            profile-derived expectations (Path A enrichment). Does not itself run
            profiling -- the caller (Path A) supplies enriched *suites*.
        dialect: cast dialect threaded into the dbt projects (``"duckdb"`` default;
            ``"spark"`` / ``"databricks"`` for the warehouse legs).
        gold_targets: table names to additionally compile a SINGLE-target gold SQL
            plan for via ``generate_sql_plan``. ``None`` = no per-table gold plans.
        suites: optional precompiled expectation lists keyed by table name. When a
            table is present, its list is persisted verbatim as the compiled suite
            (this is how Path A injects profile-enriched expectations); otherwise
            the baseline suite is generated from the UMF here.

    Returns:
        The :class:`CompiledArtifacts` manifest (already written to disk).
    """
    raise NotImplementedError


def _compile_table(
    umf: UMF,
    root: Path,
    *,
    dialect: str,
    suite: list[dict] | None,
    emit_gold_plan: bool,
    related: list[UMF],
):
    """Compile + persist every per-table artifact for *umf*; return TableArtifacts.

    Runs the per-table seams (ingest sql, ddl, pyspark, json, baseline suite,
    single-table dbt project, optional single-target gold plan) and writes each to
    its pinned path. *related* is the rest of the UMF set (needed by the gold plan
    and the single-table dbt project's FK resolution).
    """
    raise NotImplementedError


def _compile_baseline_suite(umf: UMF) -> list[dict]:
    """Generate the COMPILED baseline expectation suite for *umf*.

    Thin wrapper over ``BaselineExpectationGenerator.generate_baseline_expectations``
    (structural + column + cross-column, raw and ingested stages co-mingled).
    """
    raise NotImplementedError
