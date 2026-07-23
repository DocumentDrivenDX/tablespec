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

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from tablespec.e2e.manifest import (
    CompiledArtifacts,
    TableArtifacts,
    ddl_path,
    dbt_gold_project_dir,
    dbt_ingest_project_dir,
    gold_plan_path,
    ingest_sql_path,
    json_schema_path,
    key_candidates_path,
    ldp_project_dir,
    pyspark_schema_path,
    suite_path,
    umf_snapshot_path,
)

if TYPE_CHECKING:
    from tablespec.models.umf import UMF


def _write(path: Path, text: str) -> Path:
    """Create parents and write *text* to *path*; return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def compile_umfs(
    umfs: list[UMF],
    out_dir: str | Path,
    *,
    source: str,
    profile_enriched: bool = False,
    dialect: str = "duckdb",
    gold_targets: list[str] | None = None,
    suites: dict[str, list[dict]] | None = None,
    infer_keys: str = "none",
    key_candidates: dict[str, list[dict[str, Any]]] | None = None,
    key_promotion_min_score: float = 0.9,
    key_promotion_min_gap: float = 0.05,
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
        dialect: public cast dialect (``"duckdb"`` default; ``"spark"`` /
            ``"databricks"`` for warehouse legs). ``databricks`` is an accepted
            public spelling; Spark-family emitters may normalize it to ``spark``
            internally because cast SQL is identical.
        gold_targets: table names to additionally compile a SINGLE-target gold SQL
            plan for via ``generate_sql_plan``. ``None`` = no per-table gold plans.
        suites: optional precompiled expectation lists keyed by table name. When a
            table is present, its list is persisted verbatim as the compiled suite
            (this is how Path A injects profile-enriched expectations); otherwise
            the baseline suite is generated from the UMF here.
        infer_keys: ``"none"``, ``"candidates"``, or ``"auto"``. Candidate mode
            writes advisory sidecars only. Auto mode may promote one clear
            candidate into the compiled UMF snapshot.
        key_candidates: optional advisory key-candidate evidence keyed by table.

    Returns:
        The :class:`CompiledArtifacts` manifest (already written to disk).
    """
    from tablespec.dbt.project import generate_dbt_dag_project
    from tablespec.ldp.project import generate_ldp_project

    root = Path(out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    suites = suites or {}
    key_candidates = key_candidates or {}
    targets = set(gold_targets or [])

    # --- per-table seams ------------------------------------------------------
    tables: dict[str, TableArtifacts] = {}
    for umf in umfs:
        related = [u for u in umfs if u.table_name != umf.table_name]
        tables[umf.table_name] = _compile_table(
            umf,
            root,
            dialect=dialect,
            suite=suites.get(umf.table_name),
            infer_keys=infer_keys,
            key_candidates=key_candidates.get(umf.table_name),
            key_promotion_min_score=key_promotion_min_score,
            key_promotion_min_gap=key_promotion_min_gap,
            emit_gold_plan=umf.table_name in targets,
            related=related,
        )

    # --- whole-compile seams (one project each, spanning every table) ---------
    # Multi-table GOLD dbt DAG project (distinct from the single-target gold plan).
    dbt_gold_root: Path | None = None
    try:
        generate_dbt_dag_project(
            list(umfs), dialect=dialect, out_dir=dbt_gold_project_dir(root)
        )
        dbt_gold_root = dbt_gold_project_dir(root)
    except Exception:
        # A gold DAG is only well-formed when the set actually derives gold tables
        # (fail-closed on dangling refs / no gold target). A pure-ingest set has no
        # gold project; that is expected, so the project is simply absent.
        dbt_gold_root = None

    ldp_root: Path | None = None
    try:
        generate_ldp_project(list(umfs), dialect=dialect, out_dir=ldp_project_dir(root))
        ldp_root = ldp_project_dir(root)
    except Exception:
        ldp_root = None

    artifacts = CompiledArtifacts(
        root=root,
        source=source,
        profile_enriched=profile_enriched,
        dialect=dialect,
        tables=tables,
        dbt_gold_project=dbt_gold_root,
        ldp_project=ldp_root,
    )
    artifacts.write()
    return artifacts


def _compile_table(
    umf: UMF,
    root: Path,
    *,
    dialect: str,
    suite: list[dict] | None,
    infer_keys: str,
    key_candidates: list[dict[str, Any]] | None,
    key_promotion_min_score: float,
    key_promotion_min_gap: float,
    emit_gold_plan: bool,
    related: list[UMF],
) -> TableArtifacts:
    """Compile + persist every per-table artifact for *umf*; return TableArtifacts.

    Runs the per-table seams (ingest sql, ddl, pyspark, json, baseline suite,
    single-table dbt project, optional single-target gold plan) and writes each to
    its pinned path. *related* is the rest of the UMF set (needed by the gold plan
    and the single-table dbt project's FK resolution).
    """
    from tablespec.dbt.single_table import generate_dbt_project
    from tablespec.schemas.generators import (
        generate_json_schema,
        generate_pyspark_schema,
        generate_sql_ddl,
    )
    from tablespec.schemas.ingest_generator import generate_ingest_sql
    from tablespec.schemas.sql_generator import generate_sql_plan

    name = umf.table_name
    umf_data = umf.model_dump(exclude_none=True)
    sorted_candidates = _sorted_key_candidates(key_candidates or [])
    promotion = _promotion_decision(
        sorted_candidates,
        mode=infer_keys,
        min_score=key_promotion_min_score,
        min_gap=key_promotion_min_gap,
    )
    if promotion["promoted"]:
        umf_data["primary_key"] = promotion["columns"]

    # 0. snapshot the UMF the compile ran against (audit + reproducibility).
    umf_snap = _write(
        umf_snapshot_path(root, name),
        yaml.safe_dump(umf_data, sort_keys=False, allow_unicode=True),
    )

    # 1. ingest SQL (raw DDL + typed DDL + raw->ingested transform).
    ingest = _write(
        ingest_sql_path(root, name), generate_ingest_sql(umf_data, dialect=dialect)
    )

    # 2. schema generators.
    ddl = _write(ddl_path(root, name), generate_sql_ddl(umf_data))
    pyspark = _write(pyspark_schema_path(root, name), generate_pyspark_schema(umf_data))
    json_schema = _write(
        json_schema_path(root, name),
        json.dumps(generate_json_schema(umf_data), indent=2) + "\n",
    )

    # 3. compiled validation suite (baseline OR profile-enriched, persisted verbatim).
    suite_exps = suite if suite is not None else _compile_baseline_suite(umf_data)
    suite_json = _write(suite_path(root, name), json.dumps(suite_exps, indent=2) + "\n")
    key_candidates_json: Path | None = None
    if infer_keys in {"candidates", "auto"}:
        sidecar = {
            "table_name": name,
            "mode": infer_keys,
            "promotion": promotion,
            "candidates": sorted_candidates,
        }
        key_candidates_json = _write(
            key_candidates_path(root, name),
            json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
        )

    # 4. single-table ingest dbt project (writes its own tree under out_dir).
    dbt_ingest_root = dbt_ingest_project_dir(root, name)
    generate_dbt_project(umf_data, dialect=dialect, out_dir=dbt_ingest_root)

    # 5. SINGLE-target gold SQL plan (distinct from the multi-table dbt DAG).
    gold_plan: Path | None = None
    if emit_gold_plan:
        related_map = {u.table_name: u for u in related}
        gold_plan = _write(
            gold_plan_path(root, name),
            generate_sql_plan(umf, related_map, mode="views"),
        )

    return TableArtifacts(
        table_name=name,
        umf_snapshot=umf_snap,
        ingest_sql=ingest,
        ddl_sql=ddl,
        pyspark_schema=pyspark,
        json_schema=json_schema,
        suite_json=suite_json,
        key_candidates_json=key_candidates_json,
        dbt_ingest_project=dbt_ingest_root,
        gold_plan_sql=gold_plan,
    )


def _compile_baseline_suite(umf_data: dict) -> list[dict]:
    """Generate the COMPILED baseline expectation suite for *umf_data*.

    Thin wrapper over ``BaselineExpectationGenerator.generate_baseline_expectations``
    (structural + column + cross-column, raw and ingested stages co-mingled).
    """
    from tablespec.gx_baseline import BaselineExpectationGenerator

    return BaselineExpectationGenerator().generate_baseline_expectations(umf_data)


def _sorted_key_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates in deterministic promotion/sidecar order."""

    def score(candidate: dict[str, Any]) -> float:
        evidence = candidate.get("evidence") or {}
        raw_score = evidence.get("score", 0.0)
        return float(raw_score or 0.0)

    return sorted(
        candidates,
        key=lambda candidate: (
            -score(candidate),
            len(candidate.get("columns") or []),
            tuple(candidate.get("columns") or []),
        ),
    )


def _promotion_decision(
    candidates: list[dict[str, Any]],
    *,
    mode: str,
    min_score: float,
    min_gap: float,
) -> dict[str, Any]:
    """Decide whether an advisory candidate can become authoritative UMF PK."""
    if mode != "auto":
        return {
            "promoted": False,
            "reason": "mode is advisory-only",
            "columns": [],
        }

    qualifying = [
        candidate
        for candidate in candidates
        if _is_promotable_key_candidate(candidate, min_score=min_score)
    ]
    if not qualifying:
        return {
            "promoted": False,
            "reason": "no candidate met auto-promotion criteria",
            "columns": [],
        }
    if len(qualifying) > 1:
        top_score = _candidate_score(qualifying[0])
        runner_up_score = _candidate_score(qualifying[1])
        if top_score - runner_up_score < min_gap:
            return {
                "promoted": False,
                "reason": "candidate score gap below key_promotion_min_gap",
                "columns": [],
            }

    winner = qualifying[0]
    return {
        "promoted": True,
        "reason": "single clear verified key candidate promoted",
        "columns": list(winner.get("columns") or []),
        "downstream_effects": [
            "sample data uniqueness tracking may change",
            "dbt incremental MERGE unique_key may change",
            "LDP APPLY CHANGES KEYS may change",
        ],
    }


def _candidate_score(candidate: dict[str, Any]) -> float:
    evidence = candidate.get("evidence") or {}
    return float(evidence.get("score") or 0.0)


def _is_promotable_key_candidate(
    candidate: dict[str, Any], *, min_score: float
) -> bool:
    evidence = candidate.get("evidence") or {}
    return (
        candidate.get("kind") == "primary_key_candidate"
        and candidate.get("verified_exact") is True
        and candidate.get("exact_unique") is True
        and evidence.get("nullable") is False
        and evidence.get("minimal") is True
        and _candidate_score(candidate) >= min_score
    )
