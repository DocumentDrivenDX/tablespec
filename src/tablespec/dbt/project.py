"""Generate a multi-table GOLD dbt project from a UMF set (the DAG emitter).

Pipeline (corrected design, IR-first):

  1. :class:`~tablespec.dbt.registry.NodeRegistry` builds the logical-plan IR from
     the whole UMF set and the physical-name -> node index. Cycles fail loudly.
  2. Materialization is decided on that graph by
     :class:`~tablespec.dbt.materialization.MaterializationPolicy`.
  3. Rendering: staging models reuse the shared ``build_ingest_select`` cast
     SELECT; gold models reuse the core ``SQLPlanGenerator`` with a
     :class:`~tablespec.dbt.renderer.DbtRefRenderer` injected, so every inter-table
     relation becomes a static ``{{ ref() }}`` / ``{{ source() }}`` literal and the
     temp-view step chain collapses into CTEs inside one ``gold_<t>`` model.

The function returns ``{relative_path: contents}`` (optionally written to disk),
so it is golden-testable and runnable by ``dbt parse``/``compile``/``run`` against
duckdb.

All dbt-specific logic is contained in ``tablespec.dbt``; the core
(``build_ingest_select``, ``SQLPlanGenerator``, the ``TableRenderer`` seam, the IR)
has no dbt dependency.
"""

from __future__ import annotations

from pathlib import Path

from tablespec.core.ir import NodeRole
from tablespec.dbt.materialization import Materialization, MaterializationPolicy
from tablespec.dbt.registry import NodeRegistry
from tablespec.dbt.renderer import DbtRefRenderer
from tablespec.dbt.routing import RoutingPolicy
from tablespec.models.umf import UMF
from tablespec.schemas.generators import _resolve_nullable
from tablespec.schemas.ingest_generator import build_ingest_select
from tablespec.schemas.sql_generator import SQLPlanGenerator


class DbtProjectError(ValueError):
    """Raised on an un-renderable project (cycle, dangling ref, etc.)."""


# ---------------------------------------------------------------------------
# Config block rendering
# ---------------------------------------------------------------------------


def _config_block(mat: Materialization) -> str:
    """Render the dbt ``{{ config(...) }}`` block for a materialization."""
    lines = ["{{", "    config("]
    lines.append(f"        materialized='{mat.strategy}',")
    if mat.incremental_strategy:
        lines.append(f"        incremental_strategy='{mat.incremental_strategy}',")
    if mat.unique_key:
        keys = ", ".join(f'"{k}"' for k in mat.unique_key)
        lines.append(f"        unique_key=[{keys}],")
    lines.append("    )")
    lines.append("}}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Staging (ingested_<t>) models
# ---------------------------------------------------------------------------


def _staging_model_sql(
    umf: UMF,
    mat: Materialization,
    routing: RoutingPolicy,
    *,
    dialect: str,
) -> str:
    """Render an ``ingested_<t>`` staging model body (raw -> typed cast SELECT)."""
    umf_data = umf.model_dump(exclude_none=True)
    ingest = build_ingest_select(umf_data, dialect=dialect)
    source = routing.source_literal(f"raw_{umf.table_name}")
    config = _config_block(mat)

    if ingest.has_dedup:
        body = (
            "-- incremental + primary_key: dbt MERGEs on unique_key.\n"
            "-- The dedup-latest window keeps the newest row per key in the batch.\n"
            f"SELECT\n{ingest.select_block}\n"
            "FROM (\n"
            f"{ingest.dedup_window_sql(source)}\n"
            ") AS src_raw"
        )
    elif ingest.mode == "incremental":
        body = (
            "-- WARNING: no primary_key + incremental -> blind append (no dedup).\n"
            f"SELECT\n{ingest.select_block}\nFROM {source}"
        )
    else:
        body = (
            "-- snapshot: full drop/reload (materialized table rebuild).\n"
            f"SELECT\n{ingest.select_block}\nFROM {source}"
        )
    return f"{config}\n\n{body}\n"


# ---------------------------------------------------------------------------
# Gold (gold_<t>) models
# ---------------------------------------------------------------------------


def _gold_model_sql(
    umf: UMF,
    registry: NodeRegistry,
    mat: Materialization,
    routing: RoutingPolicy,
) -> str:
    """Render a ``gold_<t>`` model: the SQLPlanGenerator plan collapsed to CTEs.

    Inter-table relations are rendered as ``{{ ref('ingested_<other>') }}`` by the
    injected :class:`DbtRefRenderer`; the temp-view step chain is converted to a
    single ``WITH ... SELECT`` (cte mode) so the whole gold table is one model.

    Materialization note: every generated step of a gold table (``disposition_*``,
    ``*_agg``, ``*_first``, ``member_universe``) is PRIVATE to that one gold model
    and consumed exactly once, so the design's policy (ephemeral/inline for cheap,
    single-fanout, private steps) reduces to inlining them as CTEs here -- which is
    exactly what cte mode does. Promoting a step to its own materialized node only
    pays off when it is SHARED across >=2 gold models; cross-gold step sharing is
    not produced by the current single-table planner, so no per-step IR nodes are
    emitted. If that changes, add INTERMEDIATE nodes in the registry and let
    :meth:`MaterializationPolicy.for_node` decide table-vs-ephemeral on fanout.
    """
    renderer = DbtRefRenderer(registry, routing)
    generator = SQLPlanGenerator(table_renderer=renderer)
    related = {u.table_name: u for u in registry.all_umfs()}
    # cte mode collapses the CREATE TEMP VIEW chain into one WITH ... SELECT.
    plan_sql = generator.generate_for_table(umf, related, mode="cte")
    # A dbt model body is a single SELECT with NO terminating ';' (dbt wraps it in
    # a CREATE ... AS ( ... )); strip the statement terminator the CTE emitter adds.
    plan_sql = plan_sql.rstrip().rstrip(";")
    config = _config_block(mat)
    return f"{config}\n\n{plan_sql.rstrip()}\n"


# ---------------------------------------------------------------------------
# sources.yml / schema.yml
# ---------------------------------------------------------------------------


def _sources_yml(registry: NodeRegistry, routing: RoutingPolicy) -> str:
    """Declare the local ``raw_<t>`` landing tables and any external relations.

    Two source groups: ``raw`` (this pipeline's all-STRING landing tables) and --
    only when present -- ``external`` (explicitly cross-pipeline references that
    fail-open by design to a ``source('external', ...)`` leaf).
    """
    nodes = sorted(registry.plan.nodes.values(), key=lambda n: n.node_id)
    raw_nodes = [n for n in nodes if n.role is NodeRole.SOURCE and not n.external]
    ext_nodes = [n for n in nodes if n.role is NodeRole.SOURCE and n.external]

    lines = ["version: 2", "", "sources:", f"  - name: {routing.source_name}"]
    if routing.raw_database:
        lines.append(f"    database: {routing.raw_database}")
    lines.append(f"    schema: {routing.raw_schema}")
    lines.append("    tables:")
    for node in raw_nodes:
        lines.append(f"      - name: {node.node_id}")

    if ext_nodes:
        lines.append("  - name: external")
        lines.append(f"    schema: {routing.raw_schema}")
        lines.append("    tables:")
        for node in ext_nodes:
            lines.append(f"      - name: {node.node_id}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _staging_schema_yml(umf: UMF) -> list[str]:
    """schema.yml entry for an ``ingested_<t>`` model: not_null / unique tests."""
    umf_data = umf.model_dump(exclude_none=True)
    pk = umf_data.get("primary_key") or []
    unique_cols: set[str] = set()
    if len(pk) == 1:
        unique_cols.add(pk[0])
    for uc in umf_data.get("unique_constraints") or []:
        if isinstance(uc, str):
            unique_cols.add(uc)
        elif isinstance(uc, list) and len(uc) == 1:
            unique_cols.add(uc[0])

    lines = [f"  - name: ingested_{umf.table_name}"]
    if umf.description:
        lines.append(f"    description: {_yaml_scalar(umf.description)}")
    lines.append("    columns:")
    for col in umf_data["columns"]:
        name = col["name"]
        not_null = not _resolve_nullable(col.get("nullable"))
        is_unique = name in unique_cols
        lines.append(f"      - name: {name}")
        if not_null or is_unique:
            lines.append("        data_tests:")
            if not_null:
                lines.append("          - not_null")
            if is_unique:
                lines.append("          - unique")
    return lines


def _gold_schema_yml(umf: UMF, registry: NodeRegistry) -> list[str]:
    """schema.yml entry for a ``gold_<t>`` model: FK relationships tests.

    A UMF ``foreign_keys`` entry ``column -> references_table.references_column``
    becomes a dbt ``relationships`` test on the gold model's column, pointing at
    the referenced table's ingested staging model. Cross-pipeline / external FKs
    are skipped (they are not model edges, per the design's "stays OUT" list).
    """
    lines = [f"  - name: gold_{umf.table_name}"]
    if umf.description:
        lines.append(f"    description: {_yaml_scalar(umf.description)}")

    fks = []
    if umf.relationships and umf.relationships.foreign_keys:
        fks = [
            fk
            for fk in umf.relationships.foreign_keys
            if not fk.cross_pipeline
            and registry.resolve(fk.references_table) is not None
        ]
    if not fks:
        return lines

    lines.append("    columns:")
    for fk in sorted(fks, key=lambda f: f.column):
        resolved = registry.resolve(fk.references_table)
        # Point the relationship at the resolved node (ingested staging for a
        # landing table, gold model for a pure-gold table). resolved is non-None
        # here -- fks were filtered to registry-known, non-cross-pipeline refs.
        assert resolved is not None
        ref_node = resolved.node_id
        lines.append(f"      - name: {fk.column}")
        lines.append("        data_tests:")
        lines.append("          - relationships:")
        lines.append("              arguments:")
        lines.append(f"                to: ref('{ref_node}')")
        lines.append(f"                field: {fk.references_column}")
    return lines


def _schema_yml(registry: NodeRegistry) -> str:
    """Assemble the project-wide schema.yml for all staging + gold models."""
    lines = ["version: 2", "", "models:"]
    for umf in registry.all_umfs():
        if umf.table_name in registry.staging_tables:
            lines.extend(_staging_schema_yml(umf))
    for umf in registry.all_umfs():
        if umf.table_name in registry.gold_tables:
            lines.extend(_gold_schema_yml(umf, registry))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# project / profiles scaffolding
# ---------------------------------------------------------------------------


def _dbt_project_yml(project_name: str) -> str:
    return (
        f"name: '{project_name}'\n"
        "version: '1.0.0'\n"
        "config-version: 2\n"
        "\n"
        f"profile: '{project_name}'\n"
        "\n"
        'model-paths: ["models"]\n'
        'target-path: "target"\n'
        'clean-targets: ["target", "dbt_packages"]\n'
    )


def _profiles_yml(project_name: str) -> str:
    return (
        f"{project_name}:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        "      path: \"{{ env_var('DBT_DUCKDB_PATH', 'gold.duckdb') }}\"\n"
        "      threads: 1\n"
        "      settings:\n"
        "        TimeZone: 'UTC'\n"
    )


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def generate_dbt_dag_project(
    umfs: list[UMF],
    *,
    dialect: str = "duckdb",
    out_dir: str | Path | None = None,
    project_name: str = "tablespec_gold",
    routing: RoutingPolicy | None = None,
    materialization: MaterializationPolicy | None = None,
) -> dict[str, str]:
    """Generate a multi-table GOLD dbt project from a UMF set.

    Builds the logical-plan IR (failing loudly on a cycle), decides
    materialization on the graph, then renders one ``ingested_<t>`` staging model
    per table and one ``gold_<t>`` model per table with cross-table derivations,
    plus ``sources.yml`` / ``schema.yml`` / project scaffolding.

    Args:
        umfs: the table set (UMF models).
        dialect: cast dialect for staging models (``"duckdb"`` default).
        out_dir: if given, files are also written under this directory.
        project_name: dbt project + profile name.
        routing: source/model :class:`RoutingPolicy` (dev/prod placement).
        materialization: override :class:`MaterializationPolicy`.

    Returns:
        ``{relative_path: file_contents}`` for the whole project.

    Raises:
        DbtProjectError: the UMF graph has a dependency cycle, or a gold model
            references a relation that is neither a known table nor external.
    """
    routing = routing or RoutingPolicy()
    policy = materialization or MaterializationPolicy()

    registry = NodeRegistry(list(umfs))

    # FAIL CLOSED: a gold table that references a relation present in no UMF (and
    # not marked external) is an error -- never silently drop the dependency nor
    # emit a phantom source('external', ...).
    if registry.dangling_refs:
        pairs = ", ".join(
            f"{tbl} -> {ref!r}" for tbl, ref in sorted(registry.dangling_refs)
        )
        msg = (
            "Gold table(s) reference unknown, non-external relations "
            f"(fail closed): {pairs}. Add the table to the UMF set or mark the "
            "reference external."
        )
        raise DbtProjectError(msg)

    cycle = registry.plan.detect_cycle()
    if cycle is not None:
        msg = "UMF dependency graph has a cycle: " + " -> ".join(cycle)
        raise DbtProjectError(msg)

    files: dict[str, str] = {
        "dbt_project.yml": _dbt_project_yml(project_name),
        "profiles.yml": _profiles_yml(project_name),
        "models/sources.yml": _sources_yml(registry, routing),
        "models/schema.yml": _schema_yml(registry),
    }

    # Staging models (one per real landing table; pure-gold tables have none).
    for umf in registry.all_umfs():
        if umf.table_name not in registry.staging_tables:
            continue
        node = registry.plan.nodes[f"ingested_{umf.table_name}"]
        assert node.role is NodeRole.INGESTED
        umf_data = umf.model_dump(exclude_none=True)
        ingestion = umf_data.get("ingestion") or {}
        mode = ingestion.get("mode", "incremental")
        mat = policy.for_ingested(
            mode=mode, primary_key=umf_data.get("primary_key") or []
        )
        files[f"models/staging/ingested_{umf.table_name}.sql"] = _staging_model_sql(
            umf, mat, routing, dialect=dialect
        )

    # Gold models (only tables with cross-table derivations).
    for umf in registry.all_umfs():
        if umf.table_name not in registry.gold_tables:
            continue
        node = registry.plan.nodes[f"gold_{umf.table_name}"]
        mat = policy.for_node(node, registry.plan, table_name=umf.table_name)
        files[f"models/marts/gold_{umf.table_name}.sql"] = _gold_model_sql(
            umf, registry, mat, routing
        )

    if out_dir is not None:
        base = Path(out_dir)
        for rel, content in files.items():
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

    return files


__all__ = ["DbtProjectError", "generate_dbt_dag_project"]
