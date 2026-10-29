# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generate a Lakeflow Declarative Pipelines (LDP) project from a UMF set (PROTOTYPE).

This is the EXPLORATORY sibling of ``tablespec.dbt.generate_dbt_dag_project``: it
proves the shared core (the logical-plan IR / ``NodeRegistry``,
``build_ingest_select``, ``cast_column_sql``, the ``TableRenderer`` Protocol) is
target-agnostic by emitting an LDP pipeline from the SAME inputs the dbt emitter
consumes -- without touching ``tablespec.dbt`` or the direct-SQL path.

LDP (Lakeflow Declarative Pipelines, the rebrand of Delta Live Tables) inverts the
ordered-script model: you DECLARE datasets and Databricks owns the DAG, ordering,
incrementalisation and orchestration. The model maps as:

  * raw landing -> ``CREATE OR REFRESH STREAMING TABLE <raw> AS SELECT * FROM
    STREAM read_files(<path>, format => ...)`` (continuous file ingestion).
  * ingested, incremental + primary_key -> a STREAMING TABLE shell carrying the
    EXPECTATIONS, then ``APPLY CHANGES INTO <ingested> FROM (SELECT <casts> FROM
    STREAM <raw>) KEYS (<pk>) SEQUENCE BY <order_by>``. This REPLACES the
    hand-written dedup-window + MERGE of the dbt/direct paths -- Databricks owns
    the upsert + latest-per-key.
  * ingested, incremental, no primary_key -> a STREAMING TABLE that appends the
    cast SELECT over the raw STREAM (no key, no dedup).
  * ingested, snapshot -> a MATERIALIZED VIEW (full reload of the cast SELECT).
  * gold -> a MATERIALIZED VIEW whose body is the SAME ``SQLPlanGenerator`` plan
    the dbt path renders, but with an :class:`~tablespec.ldp.renderer.LdpRefRenderer`
    injected so every inter-dataset reference is a bare LDP dataset name.

The CASTS in every dataset body are ``cast_column_sql`` output (via
``build_ingest_select``) -- the exact same source of truth as the dbt/direct
paths. The cast logic is NOT forked.

HONEST LIMITS (PROTOTYPE): LDP runs ONLY on Databricks; there is no Databricks in
this environment, so the generated SQL is NOT executed end-to-end here. The
streaming runtime (read_files autoloader, APPLY CHANGES, continuous updates) is
likewise untested. What IS tested is the generated SQL's structure, the cast
parity against duckdb, and fail-closed routing -- see the LDP tests.
"""

from __future__ import annotations

from pathlib import Path
import json

from tablespec.core.ir import NodeRole
from tablespec.core.registry import NodeRegistry, NodeRegistryError
from tablespec.ldp.expectations import derive_comments, derive_expectations
from tablespec.ldp.capability import (
    assess_ldp_readiness,
    capability_for_umf,
    invocation_manifest,
)
from tablespec.ldp.renderer import LdpRefRenderer
from tablespec.models.umf import UMF
from tablespec.schemas.ingest_generator import IngestSelect, build_ingest_select
from tablespec.schemas.sql_generator import SQLPlanGenerator


class LdpProjectError(ValueError):
    """Raised on an un-renderable LDP project (cycle, dangling ref, collision)."""


# ---------------------------------------------------------------------------
# raw streaming tables
# ---------------------------------------------------------------------------


def _raw_streaming_table(table: str, *, file_format: str) -> str:
    """Render the ``CREATE OR REFRESH STREAMING TABLE raw_<t>`` autoloader dataset.

    Reads new files continuously from the landing path via ``read_files`` inside a
    ``STREAM(...)`` -- the LDP/autoloader idiom. The raw dataset is all-string
    (the cast happens in the ingested dataset), so this is a passthrough.
    """
    raw = f"raw_{table}"
    path = f"${{landing_path}}/{table}"
    return (
        f"CREATE OR REFRESH STREAMING TABLE {raw}\n"
        f"COMMENT 'Raw landing for {table} (continuous file ingestion).'\n"
        "AS SELECT *\n"
        f"FROM STREAM read_files(\n"
        f"  '{path}',\n"
        f"  format => '{file_format}'\n"
        ");"
    )


def _read_files_format(umf: UMF, *, default: str) -> str:
    """Return the LDP ``read_files`` format derived from the UMF source kind."""
    source = umf.effective_source()
    if source.kind == "parquet":
        return "parquet"
    if source.kind != "delimited":
        raise LdpProjectError(
            f"LDP raw landing only supports delimited/parquet sources; "
            f"{umf.table_name} declares kind={source.kind!r}"
        )
    return default


def _raw_delta_streaming_table(table: str, delta_source: dict, raw_target: str) -> str:
    """Render a Delta stream with its source boundary and exact scope filter."""
    qualified = ".".join(f"`{part}`" for part in delta_source["table"].split("."))
    identity_scope = delta_source["identity_scope"]
    scope_filter = " AND ".join(
        f"`{key}` = '{value.replace(chr(39), chr(39) * 2)}'"
        for key, value in identity_scope.items()
    )
    return (
        f"CREATE OR REFRESH STREAMING TABLE {raw_target}\n"
        f"COMMENT 'Append stream for {table}, scoped by declared processing identity.'\n"
        f"AS SELECT * FROM STREAM {qualified} WITH (STARTINGVERSION={delta_source['starting_version']})\n"
        f"WHERE {scope_filter};"
    )


def _revision_pipeline_module(table: str, capability) -> str:
    """Emit a stateful append graph whose archive facts cannot be retracted."""
    declaration = json.dumps(
        {
            "source": capability.source.model_dump(mode="json"),
            "revisions": capability.revisions.model_dump(mode="json"),
            "transform": capability.transform.model_dump(mode="json"),
            "archive": capability.archive.model_dump(mode="json", by_alias=True),
            "required_dependencies": capability.required_dependencies,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    template = """# Generated by tablespec.ldp; edits will be overwritten.
import json

from pyspark import pipelines as dp
from pyspark.sql import functions as F, types as T

from tablespec.ldp.capability import LdpCapability
from tablespec.ldp.stateful import make_revision_processor, make_sequence_processor

CAPABILITY = LdpCapability.model_validate(json.loads(@@DECLARATION@@))
TABLE = @@TABLE@@
_SCOPE = CAPABILITY.source.identity_scope.model_dump(mode="python")
_POLICY = CAPABILITY.revisions
_ARCHIVE = CAPABILITY.archive
_RAW_TARGET = _ARCHIVE.raw_target
_SEQUENCE_TARGET = _ARCHIVE.sequence_decisions_target
_FACT_EVENTS_TARGET = _ARCHIVE.fact_events_target
_SCOPE_COLUMNS = list(_SCOPE)
_SEQUENCE = _POLICY.delivery_sequence
_REVISION_GROUP = [*_SCOPE_COLUMNS, _POLICY.record_id, _POLICY.record_revision]
_INTERNAL_SCHEMA = T.StructType([
    *[T.StructField(name, T.StringType(), False) for name in _SCOPE_COLUMNS],
    T.StructField("event_type", T.StringType(), False),
    T.StructField("delivery_sequence", T.LongType(), True),
    T.StructField("record_id", T.StringType(), True),
    T.StructField("record_revision", T.LongType(), True),
    T.StructField("content_hash", T.StringType(), True),
    T.StructField("payload_json", T.StringType(), True),
    T.StructField("record_sha256", T.StringType(), True),
    T.StructField("disposition", T.StringType(), True),
    T.StructField("reason_code", T.StringType(), True),
    T.StructField("evidence_json", T.StringType(), True),
    T.StructField("event_order", T.LongType(), False),
    T.StructField("item_json", T.StringType(), True),
    T.StructField("wire_json", T.StringType(), True),
])
_ARCHIVE_SCHEMA = T.StructType([
    T.StructField(name, T.LongType() if kind == "long" else T.StringType(), name in {"delivery_sequence", "record_revision"})
    # ``schema`` is the serialized alias of ArchiveBinding.archive_schema, but
    # BaseModel also exposes a ``schema()`` method. Use the Python field name
    # here so generated modules do not resolve the method instead of the map.
    for name, kind in _ARCHIVE.archive_schema.items()
])

def _identity_keyed_stream(stream):
    for key, value in _SCOPE.items():
        stream = stream.filter(F.col(key) == F.lit(value))
    for name in (_POLICY.delivery_sequence, _POLICY.record_revision):
        field = next((item for item in stream.schema.fields if item.name == name), None)
        if field is None or not isinstance(field.dataType, T.LongType):
            raise TypeError(f"{name} must be a physical BIGINT/LongType before stateful processing")
    return stream

@dp.table(name=_SEQUENCE_TARGET, comment="Checkpoint-backed exact replay/conflict decisions keyed by scoped BIGINT sequence.")
def sequence_decisions():
    stream = _identity_keyed_stream(spark.readStream.table(_RAW_TARGET))
    return (
        stream.groupBy(*_SCOPE_COLUMNS, _SEQUENCE)
        .transformWithStateInPandas(
            statefulProcessor=make_sequence_processor(CAPABILITY),
            outputStructType=_INTERNAL_SCHEMA,
            outputMode="Append",
            timeMode="None",
        )
    )

@dp.table(name=_ARCHIVE.target, comment="Append-only checkpoint-backed revision and conflict event archive.")
def revision_archive():
    decisions = spark.readStream.table(_SEQUENCE_TARGET)
    accepted = decisions.filter(F.col("event_type") == "accepted_item")
    reconstructed = (
        accepted.groupBy(*_REVISION_GROUP)
        .transformWithStateInPandas(
            statefulProcessor=make_revision_processor(CAPABILITY),
            outputStructType=_INTERNAL_SCHEMA,
            outputMode="Append",
            timeMode="None",
        )
    )
    durable_sequence_conflicts = decisions.filter(F.col("event_type") == "conflict")
    return reconstructed.unionByName(durable_sequence_conflicts).select(
        *[field.name for field in _ARCHIVE_SCHEMA.fields]
    )

@dp.table(name=_FACT_EVENTS_TARGET, comment="Append-only fact events selected from the immutable archive.")
def revision_fact_events():
    return spark.readStream.table(_ARCHIVE.target).filter(F.col("event_type") == "revision")

dp.create_streaming_table(name=_ARCHIVE.latest_target)
dp.create_auto_cdc_flow(
    target=_ARCHIVE.latest_target,
    source=_FACT_EVENTS_TARGET,
    keys=[*_SCOPE_COLUMNS, _POLICY.record_id],
    sequence_by=F.col("record_revision"),
    stored_as_scd_type=1,
)
"""
    return template.replace("@@DECLARATION@@", repr(declaration)).replace(
        "@@TABLE@@", repr(table)
    )


# ---------------------------------------------------------------------------
# ingested datasets (the materialization branch)
# ---------------------------------------------------------------------------


def _expectations_block(umf: UMF) -> tuple[str, list[str]]:
    """Return (constraints_text, comment_notes) for a dataset's EXPECTATIONS.

    ``constraints_text`` is the parenthesised ``( CONSTRAINT ... , ... )`` clause
    (empty string when there are no constraints); ``comment_notes`` are the honest
    not-row-local intents (uniqueness / FK) surfaced separately.
    """
    umf_data = umf.model_dump(exclude_none=True)
    expectations = derive_expectations(umf_data)
    if not expectations:
        constraints_text = ""
    else:
        lines = [f"  {e.render()}" for e in expectations]
        constraints_text = "(\n" + ",\n".join(lines) + "\n)"
    return constraints_text, []


def _ingested_dataset_sql(
    umf: UMF,
    registry: NodeRegistry,
    ingest: IngestSelect,
) -> str:
    """Render the ingested dataset, branching on ingestion.mode + primary_key.

    incremental + pk  -> STREAMING TABLE shell (+ EXPECTATIONS) then APPLY CHANGES.
    incremental no-pk -> STREAMING TABLE append of the cast SELECT over the STREAM.
    snapshot          -> MATERIALIZED VIEW full reload of the cast SELECT.
    """
    table = umf.table_name
    ingested = f"ingested_{table}"
    raw_stream = f"raw_{table}"
    constraints, _ = _expectations_block(umf)
    resolver = _registry_resolver(registry)
    comments = derive_comments(
        umf.model_dump(exclude_none=True), resolver, mode=ingest.mode
    )
    comment_block = ("\n".join(comments) + "\n") if comments else ""

    if ingest.has_dedup:
        # incremental + primary_key: a STREAMING TABLE shell holds the EXPECTATIONS,
        # then APPLY CHANGES owns the upsert + latest-per-key (replacing the
        # hand-written dedup window + MERGE). KEYS = primary_key, SEQUENCE BY =
        # order_by (the dedup ordering the dbt/direct paths used in their window).
        keys = ", ".join(ingest.primary_key)
        # APPLY CHANGES takes a SINGLE sequencing expression. One order_by column
        # is used bare; multiple are wrapped in STRUCT(...) (the Databricks idiom
        # for multi-column sequencing) so the lexicographic ordering is preserved.
        sequence_by = (
            ingest.order_by[0]
            if len(ingest.order_by) == 1
            else f"STRUCT({', '.join(ingest.order_by)})"
        )
        shell = f"CREATE OR REFRESH STREAMING TABLE {ingested}"
        if constraints:
            shell += f"\n{constraints}"
        shell += ";"
        apply = (
            f"APPLY CHANGES INTO {ingested}\n"
            f"FROM (\n"
            "  SELECT\n"
            f"{ingest.select_block}\n"
            f"  FROM STREAM {raw_stream}\n"
            ")\n"
            f"KEYS ({keys})\n"
            f"SEQUENCE BY {sequence_by};"
        )
        return f"{comment_block}{shell}\n\n{apply}"

    if ingest.mode == "incremental":
        # keyless incremental -> append the cast SELECT over the raw STREAM. No
        # KEYS / SEQUENCE BY (nothing to dedup on); duplicates accumulate exactly
        # like the dbt blind-append / Spark INSERT INTO branch.
        header = f"CREATE OR REFRESH STREAMING TABLE {ingested}"
        if constraints:
            header += f"\n{constraints}"
        body = f"AS SELECT\n{ingest.select_block}\nFROM STREAM {raw_stream};"
        return f"{comment_block}{header}\n{body}"

    # snapshot -> MATERIALIZED VIEW full reload (NOT a stream).
    header = f"CREATE OR REFRESH MATERIALIZED VIEW {ingested}"
    if constraints:
        header += f"\n{constraints}"
    body = f"AS SELECT\n{ingest.select_block}\nFROM {raw_stream};"
    return f"{comment_block}{header}\n{body}"


# ---------------------------------------------------------------------------
# gold datasets
# ---------------------------------------------------------------------------


def _gold_dataset_sql(umf: UMF, registry: NodeRegistry) -> str:
    """Render a gold ``CREATE OR REFRESH MATERIALIZED VIEW gold_<t>`` dataset.

    Reuses the SAME ``SQLPlanGenerator`` the dbt path uses, with an
    :class:`LdpRefRenderer` injected so inter-dataset relations render as bare LDP
    dataset names. The CTE-mode plan body becomes the materialized-view SELECT;
    Databricks resolves the DAG from the referenced dataset names.
    """
    renderer = LdpRefRenderer(registry)
    generator = SQLPlanGenerator(table_renderer=renderer)
    related = {u.table_name: u for u in registry.all_umfs()}
    plan_sql = generator.generate_for_table(umf, related, mode="cte")
    # Strip the trailing statement terminator the CTE emitter adds -- LDP wraps the
    # SELECT in CREATE ... MATERIALIZED VIEW ... AS ( ... ).
    plan_sql = plan_sql.rstrip().rstrip(";").rstrip()

    constraints, _ = _expectations_block(umf)
    resolver = _registry_resolver(registry)
    # A gold dataset is a MATERIALIZED VIEW (full refresh), so PK uniqueness is not
    # APPLY-CHANGES-enforced -- the snapshot phrasing states that honestly.
    comments = derive_comments(
        umf.model_dump(exclude_none=True), resolver, mode="snapshot"
    )
    comment_block = ("\n".join(comments) + "\n") if comments else ""

    header = f"CREATE OR REFRESH MATERIALIZED VIEW gold_{umf.table_name}"
    if constraints:
        header += f"\n{constraints}"
    return f"{comment_block}{header}\nAS\n{plan_sql};"


def _registry_resolver(registry: NodeRegistry):
    """A ``resolve_target`` for ``core.schema_facts`` backed by the registry."""

    def resolve(table: str) -> str | None:
        resolved = registry.resolve(table)
        return resolved.node_id if resolved is not None else None

    return resolve


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def generate_ldp_project(
    umfs: list[UMF],
    *,
    dialect: str = "spark",
    file_format: str = "csv",
    out_dir: str | Path | None = None,
) -> dict[str, str]:
    """Generate a Lakeflow Declarative Pipelines project from a UMF set (PROTOTYPE).

    Builds the logical-plan IR (failing loudly on a cycle / dangling ref) via the
    shared ``NodeRegistry``, then emits one ``.sql`` file per dataset:

      * ``raw/raw_<t>.sql``        -- streaming-table autoloader (landing tables only),
      * ``ingested/ingested_<t>.sql`` -- APPLY CHANGES / streaming-append / mat-view
        per ``ingestion.mode`` + ``primary_key``, carrying inline EXPECTATIONS,
      * ``gold/gold_<t>.sql``      -- a materialized view (the SQLPlanGenerator plan
        with bare LDP dataset refs).

    Args:
        umfs: the table set (UMF models).
        dialect: cast dialect for ingested dataset bodies. LDP runs on Databricks/
            Spark, so the default is ``"spark"``; ``"databricks"`` and
            ``"spark"`` share the same Spark-family cast path, and ``"duckdb"`` is
            accepted so the cast-parity harness can prove the SELECT body is the
            shared cast.
        file_format: ``read_files`` format for the raw autoloader (e.g. ``csv``).
        out_dir: if given, files are also written under this directory.

    Returns:
        ``{relative_path: file_contents}`` for the whole pipeline.

    Raises:
        LdpProjectError: cycle, dangling (unknown non-external) reference, or a
            physical-name collision in the UMF set.
    """
    try:
        registry = NodeRegistry(list(umfs))
    except NodeRegistryError as exc:
        raise LdpProjectError(str(exc)) from exc

    if registry.dangling_refs:
        pairs = ", ".join(
            f"{tbl} -> {ref!r}" for tbl, ref in sorted(registry.dangling_refs)
        )
        msg = (
            "Gold dataset(s) reference unknown, non-external relations "
            f"(fail closed): {pairs}. Add the table to the UMF set or mark the "
            "reference external."
        )
        raise LdpProjectError(msg)

    cycle = registry.plan.detect_cycle()
    if cycle is not None:
        msg = "UMF dependency graph has a cycle: " + " -> ".join(cycle)
        raise LdpProjectError(msg)

    try:
        readiness = assess_ldp_readiness(list(umfs))
    except (TypeError, ValueError) as exc:
        raise LdpProjectError(f"invalid advanced LDP declaration: {exc}") from exc

    files: dict[str, str] = {}

    # Raw + ingested datasets (one per real landing table).
    for umf in registry.all_umfs():
        if umf.table_name not in registry.staging_tables:
            continue
        node = registry.plan.nodes[f"ingested_{umf.table_name}"]
        assert node.role is NodeRole.INGESTED
        umf_data = umf.model_dump(exclude_none=True)
        source = umf.effective_source()
        if getattr(source, "kind", None) == "delta":
            capability = capability_for_umf(umf)
            declared_columns = {column["name"] for column in umf_data["columns"]}
            ingest = build_ingest_select(
                umf_data,
                dialect=dialect,
                cast_type_overrides={
                    field: "BIGINT"
                    for field in (
                        capability.revisions.delivery_sequence,
                        capability.revisions.record_revision,
                    )
                    if field in declared_columns
                },
            )
            delta_source = source.model_dump(mode="json")
            files[f"raw/raw_{umf.table_name}.sql"] = _raw_delta_streaming_table(
                umf.table_name, delta_source, capability.archive.raw_target
            )
            manifest = invocation_manifest(umf.table_name, capability)
            report = readiness[umf.table_name]
            manifest["static_readiness"] = report.model_dump(mode="json")
            files[f"bindings/{umf.table_name}.json"] = (
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n"
            )
            files[f"pipeline/ldp_{umf.table_name}.py"] = _revision_pipeline_module(
                umf.table_name, capability
            )
        else:
            ingest = build_ingest_select(umf_data, dialect=dialect)
            raw_file_format = _read_files_format(umf, default=file_format)
            files[f"raw/raw_{umf.table_name}.sql"] = _raw_streaming_table(
                umf.table_name, file_format=raw_file_format
            )
        files[f"ingested/ingested_{umf.table_name}.sql"] = _ingested_dataset_sql(
            umf, registry, ingest
        )

    # Gold datasets (only tables with cross-table derivations).
    for umf in registry.all_umfs():
        if umf.table_name not in registry.gold_tables:
            continue
        files[f"gold/gold_{umf.table_name}.sql"] = _gold_dataset_sql(umf, registry)

    if out_dir is not None:
        base = Path(out_dir)
        for rel, content in files.items():
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

    return files


__all__ = ["LdpProjectError", "generate_ldp_project"]
