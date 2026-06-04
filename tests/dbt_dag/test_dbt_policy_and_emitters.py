"""Branch coverage for the dbt materialization policy and the two emitters.

Pure-Python (no dbt/duckdb invocation). Targets the corrected-design decision
points the end-to-end tests don't exercise directly:

  * MaterializationPolicy.for_node: gold-final default vs explicit-incremental;
    INTERMEDIATE ephemeral (cheap+private) vs table (expensive OR shared); the
    SOURCE/INGESTED fallthrough.
  * single_table.generate_dbt_project: the three write strategies (merge / append /
    table) and schema.yml not_null/unique (single-PK, list-unique, composite).
  * project.generate_dbt_dag_project: keyless-incremental staging, prod routing
    (raw_database), composite/nullable FK relationships, and a no-gold UMF set.
"""

from __future__ import annotations

import pytest
import yaml

from tablespec.core.ir import LogicalPlan, NodeRole, PlanNode
from tablespec.dbt import (
    Materialization,
    MaterializationPolicy,
    RoutingPolicy,
    generate_dbt_dag_project,
    generate_dbt_project,
)
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

_NN = {"default": False}
_NL = {"default": True}


def _col_tests(schema_yaml: str, model: str, column: str) -> list:
    """Parse schema.yml and return the data_tests attached to model.column."""
    doc = yaml.safe_load(schema_yaml)
    for m in doc["models"]:
        if m["name"] != model:
            continue
        for c in m.get("columns") or []:
            if c["name"] == column:
                return c.get("data_tests") or []
    return []


# ---------------------------------------------------------------------------
# MaterializationPolicy.for_node
# ---------------------------------------------------------------------------


def _plan_with(node: PlanNode, consumers: int = 0) -> LogicalPlan:
    """A plan containing *node* plus *consumers* nodes that depend on it."""
    plan = LogicalPlan()
    plan.add(node)
    for i in range(consumers):
        plan.add(
            PlanNode(
                node_id=f"consumer_{i}",
                role=NodeRole.GOLD,
                depends_on={node.node_id},
            )
        )
    return plan


def test_gold_final_defaults_to_table():
    policy = MaterializationPolicy()
    node = PlanNode(node_id="gold_g", role=NodeRole.GOLD, expensive=True)
    plan = _plan_with(node)
    mat = policy.for_node(node, plan, table_name="g")
    assert mat == Materialization(strategy="table")


def test_gold_explicit_incremental_strategy():
    policy = MaterializationPolicy(gold_incremental={"g": ("merge", ("id",))})
    node = PlanNode(node_id="gold_g", role=NodeRole.GOLD, expensive=True)
    plan = _plan_with(node)
    mat = policy.for_node(node, plan, table_name="g")
    assert mat.strategy == "incremental"
    assert mat.incremental_strategy == "merge"
    assert mat.unique_key == ("id",)


def test_intermediate_cheap_and_private_is_ephemeral():
    policy = MaterializationPolicy()
    node = PlanNode(node_id="step", role=NodeRole.INTERMEDIATE, expensive=False)
    plan = _plan_with(node, consumers=1)  # fanout == 1 -> private
    mat = policy.for_node(node, plan)
    assert mat.strategy == "ephemeral"


def test_intermediate_shared_is_table():
    policy = MaterializationPolicy()
    node = PlanNode(node_id="step", role=NodeRole.INTERMEDIATE, expensive=False)
    plan = _plan_with(node, consumers=2)  # fanout == 2 -> shared
    mat = policy.for_node(node, plan)
    assert mat.strategy == "table"


def test_intermediate_expensive_is_table_even_if_private():
    policy = MaterializationPolicy()
    node = PlanNode(node_id="step", role=NodeRole.INTERMEDIATE, expensive=True)
    plan = _plan_with(node, consumers=1)
    mat = policy.for_node(node, plan)
    assert mat.strategy == "table"


def test_intermediate_zero_fanout_is_ephemeral():
    """A cheap intermediate with no consumers (fanout 0) materializes ephemeral.

    The policy gate is ``not expensive and fanout <= 1``; a dead/unconsumed cheap
    node is therefore ephemeral (inlined and effectively pruned), never a
    standalone table. This pins the documented behaviour at the fanout boundary.
    """
    policy = MaterializationPolicy()
    node = PlanNode(node_id="step", role=NodeRole.INTERMEDIATE, expensive=False)
    plan = _plan_with(node, consumers=0)
    assert policy.for_node(node, plan).strategy == "ephemeral"


def test_source_role_falls_through_to_table():
    policy = MaterializationPolicy()
    node = PlanNode(node_id="raw_x", role=NodeRole.SOURCE)
    plan = _plan_with(node)
    assert policy.for_node(node, plan).strategy == "table"


# ---------------------------------------------------------------------------
# single_table.generate_dbt_project: write strategies + schema.yml
# ---------------------------------------------------------------------------


def _single_umf_data(
    *, mode: str, primary_key: list[str] | None = None, unique_constraints=None
) -> dict:
    data: dict = {
        "table_name": "t",
        "description": "single-table fixture",
        "ingestion": {"mode": mode},
        "columns": [
            {"name": "id", "data_type": "INTEGER", "nullable": False},
            {"name": "label", "data_type": "VARCHAR", "nullable": True},
        ],
    }
    if primary_key is not None:
        data["primary_key"] = primary_key
    if unique_constraints is not None:
        data["unique_constraints"] = unique_constraints
    return data


def test_single_incremental_pk_merges():
    files = generate_dbt_project(
        _single_umf_data(mode="incremental", primary_key=["id"]), dialect="duckdb"
    )
    model = files["models/t.sql"]
    assert "materialized='incremental'" in model
    assert "incremental_strategy='merge'" in model
    assert 'unique_key=["id"]' in model
    assert "row_number() OVER (PARTITION BY id" in model


def test_single_incremental_no_pk_appends():
    files = generate_dbt_project(
        _single_umf_data(mode="incremental", primary_key=[]), dialect="duckdb"
    )
    model = files["models/t.sql"]
    assert "materialized='incremental'" in model
    assert "merge" not in model
    assert "blind append" in model
    # single-table keyless path relies on dbt's DEFAULT incremental strategy
    # (append): it intentionally emits NO unique_key and NO incremental_strategy.
    assert "unique_key" not in model
    assert "incremental_strategy" not in model


def test_dag_keyless_incremental_policy_sets_append_strategy():
    """The DAG materialization policy makes the keyless append EXPLICIT."""
    mat = MaterializationPolicy().for_ingested(mode="incremental", primary_key=[])
    assert mat.strategy == "incremental"
    assert mat.incremental_strategy == "append"
    assert mat.unique_key == ()


def test_single_snapshot_is_table_rebuild():
    files = generate_dbt_project(
        _single_umf_data(mode="snapshot", primary_key=["id"]), dialect="duckdb"
    )
    model = files["models/t.sql"]
    assert "materialized='table'" in model
    assert "full drop/reload" in model
    assert "incremental" not in model


def test_single_schema_yml_not_null_and_unique():
    files = generate_dbt_project(
        _single_umf_data(mode="incremental", primary_key=["id"]), dialect="duckdb"
    )
    schema = files["models/schema.yml"]
    # id: non-nullable + single PK -> not_null AND unique on THAT column
    assert sorted(_col_tests(schema, "t", "id")) == ["not_null", "unique"]
    # label: nullable, not a key -> NO tests attached
    assert _col_tests(schema, "t", "label") == []
    # description rendered as a quoted scalar
    assert "single-table fixture" in schema


def test_single_schema_yml_list_unique_constraint():
    files = generate_dbt_project(
        _single_umf_data(
            mode="snapshot", primary_key=[], unique_constraints=[["label"]]
        ),
        dialect="duckdb",
    )
    schema = files["models/schema.yml"]
    # single-column list unique constraint -> a unique test on that column
    assert "- unique" in schema


def test_single_schema_yml_string_unique_constraint():
    files = generate_dbt_project(
        _single_umf_data(mode="snapshot", primary_key=[], unique_constraints=["label"]),
        dialect="duckdb",
    )
    assert "- unique" in files["models/schema.yml"]


def test_single_composite_pk_emits_no_unique_test():
    """Composite PK uniqueness is left to the merge key, not a per-column test."""
    files = generate_dbt_project(
        _single_umf_data(mode="incremental", primary_key=["id", "label"]),
        dialect="duckdb",
    )
    schema = files["models/schema.yml"]
    # neither column carries a `unique` test (composite -> no single-col unique)
    assert "- unique" not in schema
    # but the merge still keys on both
    assert 'unique_key=["id", "label"]' in files["models/t.sql"]


def test_single_project_scaffolding_present():
    files = generate_dbt_project(
        _single_umf_data(mode="snapshot", primary_key=["id"]), dialect="duckdb"
    )
    assert set(files) == {
        "dbt_project.yml",
        "profiles.yml",
        "models/sources.yml",
        "models/schema.yml",
        "models/t.sql",
    }
    assert "type: duckdb" in files["profiles.yml"]
    assert "raw_t" in files["models/sources.yml"]


# ---------------------------------------------------------------------------
# project.generate_dbt_dag_project: branches the e2e test doesn't hit
# ---------------------------------------------------------------------------


def _staging(table: str, *, mode: str, pk: list[str]) -> UMF:
    return UMF(
        version="1.0",
        table_name=table,
        primary_key=pk,
        ingestion={"mode": mode},
        columns=[
            {"name": f"{table}_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "val", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )


def test_dag_keyless_incremental_staging_appends():
    """A staging table with incremental mode and NO pk renders a blind-append body."""
    events = UMF(
        version="1.0",
        table_name="events",
        ingestion={"mode": "incremental"},
        columns=[
            {"name": "event_id", "data_type": "VARCHAR", "nullable": _NL},
            {"name": "payload", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    files = generate_dbt_dag_project([events])
    staging = files["models/staging/ingested_events.sql"]
    assert "materialized='incremental'" in staging
    assert "blind append" in staging


def test_dag_prod_routing_emits_database():
    """A RoutingPolicy with raw_database routes the source under that catalog."""
    routing = RoutingPolicy(
        source_name="raw", raw_schema="bronze", raw_database="prod_catalog"
    )
    files = generate_dbt_dag_project(
        [_staging("member", mode="snapshot", pk=["member_id"])], routing=routing
    )
    sources = files["models/sources.yml"]
    assert "database: prod_catalog" in sources
    assert "schema: bronze" in sources


def test_dag_gold_fk_relationships_test():
    """A non-cross-pipeline FK on a gold model becomes a relationships test."""
    member = _staging("member", mode="snapshot", pk=["member_id"])
    claims = UMF(
        version="1.0",
        table_name="claims",
        primary_key=["claim_id"],
        ingestion={"mode": "incremental"},
        columns=[
            {"name": "claim_id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "member_id", "data_type": "INTEGER", "nullable": _NL},
        ],
    )
    gold = UMF(
        version="1.0",
        table_name="enriched",
        primary_key=["claim_id"],
        metadata={"base_table": "claims"},
        columns=[
            {
                "name": "claim_id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "member_id",
                "data_type": "INTEGER",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "member", "column": "member_id", "priority": 1}
                    ],
                },
            },
        ],
        relationships={
            "foreign_keys": [
                {
                    "column": "member_id",
                    "references_table": "member",
                    "references_column": "member_id",
                }
            ]
        },
    )
    files = generate_dbt_dag_project([member, claims, gold])
    schema = files["models/schema.yml"]
    # The relationships test is attached to gold_enriched.member_id and points at
    # the referenced table's ingested staging model + column.
    tests = _col_tests(schema, "gold_enriched", "member_id")
    rel = next(t for t in tests if isinstance(t, dict) and "relationships" in t)
    args = rel["relationships"]["arguments"]
    assert args["to"] == "ref('ingested_member')"
    assert args["field"] == "member_id"


def test_dag_cross_pipeline_fk_is_not_a_relationships_test():
    """The cross_pipeline flag (NOT qualification) is what excludes an FK test.

    Unconfounded: the FK references a BARE, LOCALLY-KNOWN table (``member``) that
    would otherwise yield a relationships test. Only ``cross_pipeline=True`` keeps
    it out of schema.yml -- if the flag were ignored, a relationships test WOULD be
    emitted, so this test would fail. A control FK (non-cross_pipeline) on the same
    model still produces its test, proving the gold model is FK-test-capable.
    """
    member = _staging("member", mode="snapshot", pk=["member_id"])
    other = _staging("other", mode="snapshot", pk=["other_id"])
    gold = UMF(
        version="1.0",
        table_name="enriched",
        primary_key=["id"],
        metadata={"base_table": "member"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "member_id",
                "data_type": "INTEGER",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "member", "column": "member_id", "priority": 1}
                    ],
                },
            },
            {
                "name": "other_id",
                "data_type": "INTEGER",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "other", "column": "other_id", "priority": 1}
                    ],
                },
            },
        ],
        relationships={
            "foreign_keys": [
                # cross_pipeline -> excluded even though 'member' is local & known
                {
                    "column": "member_id",
                    "references_table": "member",
                    "references_column": "member_id",
                    "cross_pipeline": True,
                },
                # control: ordinary FK on the SAME model -> IS emitted
                {
                    "column": "other_id",
                    "references_table": "other",
                    "references_column": "other_id",
                },
            ]
        },
    )
    files = generate_dbt_dag_project([member, other, gold])
    schema = files["models/schema.yml"]
    # The cross_pipeline FK on member_id is NOT a relationships test...
    assert _col_tests(schema, "gold_enriched", "member_id") == []
    # ...but the ordinary FK on other_id IS (so the model is FK-test-capable).
    other_tests = _col_tests(schema, "gold_enriched", "other_id")
    assert any(isinstance(t, dict) and "relationships" in t for t in other_tests)


def test_dag_qualified_external_fk_declares_external_source():
    """A genuinely cross-pipeline (qualified, absent) ref declares an external source."""
    claims = UMF(
        version="1.0",
        table_name="claims",
        primary_key=["claim_id"],
        ingestion={"mode": "incremental"},
        metadata={"base_table": "claims"},
        columns=[
            {
                "name": "claim_id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "ext_ref",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "extpipe.refs", "column": "v", "priority": 1}
                    ],
                },
            },
        ],
    )
    files = generate_dbt_dag_project([claims])
    assert "- name: external" in files["models/sources.yml"]
    assert "extpipe__refs" in files["models/sources.yml"]


def test_dag_staging_schema_unique_constraints():
    """A staging model's list/string unique_constraints become per-column unique tests."""
    t = UMF(
        version="1.0",
        table_name="dim",
        ingestion={"mode": "snapshot"},
        unique_constraints=[["code"], ["alt_code"]],
        columns=[
            {"name": "code", "data_type": "VARCHAR", "nullable": _NN},
            {"name": "alt_code", "data_type": "VARCHAR", "nullable": _NL},
            {"name": "label", "data_type": "VARCHAR", "nullable": _NL},
        ],
    )
    files = generate_dbt_dag_project([t])
    schema = files["models/schema.yml"]
    # both single-column unique constraints surface a `unique` test
    assert schema.count("- unique") == 2


def test_dag_no_gold_only_staging():
    """A UMF set with no cross-table derivations yields staging models, no gold."""
    files = generate_dbt_dag_project([_staging("a", mode="snapshot", pk=["a_id"])])
    assert "models/staging/ingested_a.sql" in files
    assert not any(k.startswith("models/marts/") for k in files)
    # schema.yml has a models: header but no gold entries
    assert "models:" in files["models/schema.yml"]


def test_dag_determinism_independent_of_input_order():
    """File CONTENTS are independent of UMF input order (only file keys may reorder).

    sources.yml / schema.yml iterate sorted node sets, so their bytes must be
    identical regardless of the order tables are passed in -- catching ordering
    nondeterminism a same-order regenerate would miss.
    """
    member = _staging("member", mode="snapshot", pk=["member_id"])
    claims = _staging("claims", mode="incremental", pk=["claims_id"])
    forward = generate_dbt_dag_project([member, claims])
    reverse = generate_dbt_dag_project([claims, member])
    # The order-insensitive project files must be byte-identical.
    for rel in ("models/sources.yml", "dbt_project.yml", "profiles.yml"):
        assert forward[rel] == reverse[rel], f"{rel} depends on input order"
    # Same set of generated files either way.
    assert set(forward) == set(reverse)
    # And each staging model body is identical regardless of order.
    for rel in forward:
        if rel.startswith("models/staging/"):
            assert forward[rel] == reverse[rel]
