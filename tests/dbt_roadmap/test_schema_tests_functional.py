"""Functional tests for roadmap item (1): relationships + accepted_values.

These exercise the emitter over REAL UMF fixtures and assert on the PARSED YAML
of the generated ``schema.yml`` (structure, not substring greps). No mocks for
the behaviour under test. Covers the positive emission AND the negative paths
(unresolvable FK skipped, column without an in-set carries no accepted_values).

  * AC1.1 relationships emitted on the DAG path (gold model -> ingested target)
  * AC1.2 relationships emitted on the single-table path (FK resolved via related)
  * AC1.3 two single-column FKs -> two independent tests
  * AC1.5 cross-pipeline / unresolvable FK skipped
  * AC1.6 accepted_values emitted from a set-membership expectation
  * AC1.7 no spurious accepted_values for a plain column
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tablespec.dbt import generate_dbt_dag_project, generate_dbt_project
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

DAG_FIXTURES = Path(__file__).parent.parent / "fixtures" / "dbt_dag"
FK_FIXTURES = (
    Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "fk_referential"
)
AV_FIXTURES = (
    Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "accepted_values"
)


def _umf(path: Path) -> UMF:
    return UMF(**yaml.safe_load(path.read_text()))


def _model_by_name(schema_yml: str) -> dict[str, dict]:
    parsed = yaml.safe_load(schema_yml)
    return {m["name"]: m for m in parsed["models"]}


def _column_tests(model: dict, column: str) -> list:
    for col in model.get("columns", []):
        if col["name"] == column:
            return col.get("data_tests", [])
    return []


def _relationship_args(tests: list) -> list[dict]:
    out = []
    for t in tests:
        if isinstance(t, dict) and "relationships" in t:
            out.append(t["relationships"]["arguments"])
    return out


def _accepted_values_args(tests: list) -> list[dict]:
    out = []
    for t in tests:
        if isinstance(t, dict) and "accepted_values" in t:
            out.append(t["accepted_values"]["arguments"])
    return out


# ---------------------------------------------------------------------------
# AC1.1 relationships on the DAG path
# ---------------------------------------------------------------------------


def test_schema_tests_relationships_dag_preserved() -> None:
    """AC1.1 / AC1.5: gold_member_claims.member_id -> ref('ingested_member')."""
    umfs = [
        _umf(DAG_FIXTURES / f"{t}.umf.yaml")
        for t in ("member", "claims", "member_claims")
    ]
    files = generate_dbt_dag_project(umfs)
    models = _model_by_name(files["models/schema.yml"])

    gold = models["gold_member_claims"]
    args = _relationship_args(_column_tests(gold, "member_id"))
    assert args == [{"to": "ref('ingested_member')", "field": "member_id"}]

    # AC1.5: claims.member_id FK is on the gold model, NOT duplicated on the
    # ingested_claims staging model (relationships live where the FK is owned).
    ingested_claims = models["ingested_claims"]
    assert _relationship_args(_column_tests(ingested_claims, "member_id")) == []


# ---------------------------------------------------------------------------
# AC1.2 / AC1.3 / AC1.5 single-table relationships
# ---------------------------------------------------------------------------


def test_schema_tests_relationships_single_table_resolved() -> None:
    """AC1.2: single-table FK resolves via ``related`` to a bare model ref."""
    child = _umf(FK_FIXTURES / "child.umf.yaml")
    parent = _umf(FK_FIXTURES / "parent.umf.yaml")
    files = generate_dbt_project(child.model_dump(exclude_none=True), related=[parent])
    models = _model_by_name(files["models/schema.yml"])

    args = _relationship_args(_column_tests(models["child"], "parent_id"))
    assert args == [{"to": "ref('parent')", "field": "parent_id"}]

    # AC1.2: the referenced parent MUST be emitted as a real model (and a schema
    # entry + source), otherwise ref('parent') dangles and dbt silently drops the
    # relationships test. Guarding this here makes removing the parent-model
    # emission a functional failure too, not only an e2e one.
    assert "models/parent.sql" in files, sorted(files)
    assert "parent" in models, "parent model missing from schema.yml"
    assert "      - name: raw_parent" in files["models/sources.yml"]


def test_schema_tests_relationships_single_table_missing_target_skipped() -> None:
    """AC1.2/AC1.5 (skip-when-unresolvable): no ``related`` -> FK target absent ->
    NO relationships test (never a ref() to a missing model)."""
    child = _umf(FK_FIXTURES / "child.umf.yaml")
    files = generate_dbt_project(child.model_dump(exclude_none=True))  # related=None
    models = _model_by_name(files["models/schema.yml"])

    assert _relationship_args(_column_tests(models["child"], "parent_id")) == []
    # And the emitted YAML never names the unresolved parent model.
    assert "ref('parent')" not in files["models/schema.yml"]


def test_schema_tests_two_fks_two_tests() -> None:
    """AC1.3: two scalar FKs -> two independent relationships tests on their cols."""
    child = _umf(FK_FIXTURES / "child.umf.yaml")
    data = child.model_dump(exclude_none=True)
    # Add a SECOND scalar FK (child_id -> parent.parent_id) alongside the first.
    data["relationships"]["foreign_keys"].append(
        {
            "column": "child_id",
            "references_table": "parent",
            "references_column": "parent_id",
            "type": "foreign_key",
        }
    )
    parent = _umf(FK_FIXTURES / "parent.umf.yaml")
    files = generate_dbt_project(data, related=[parent])
    models = _model_by_name(files["models/schema.yml"])

    assert _relationship_args(_column_tests(models["child"], "parent_id")) == [
        {"to": "ref('parent')", "field": "parent_id"}
    ]
    assert _relationship_args(_column_tests(models["child"], "child_id")) == [
        {"to": "ref('parent')", "field": "parent_id"}
    ]


def test_schema_tests_cross_pipeline_fk_skipped() -> None:
    """AC1.5: a cross_pipeline FK emits NO relationships test."""
    child = _umf(FK_FIXTURES / "child.umf.yaml")
    data = child.model_dump(exclude_none=True)
    data["relationships"]["foreign_keys"][0]["cross_pipeline"] = True
    parent = _umf(FK_FIXTURES / "parent.umf.yaml")
    files = generate_dbt_project(data, related=[parent])
    models = _model_by_name(files["models/schema.yml"])
    assert _relationship_args(_column_tests(models["child"], "parent_id")) == []


# ---------------------------------------------------------------------------
# AC1.6 / AC1.7 accepted_values
# ---------------------------------------------------------------------------


def test_schema_tests_accepted_values_emitted_and_no_spurious() -> None:
    """AC1.6: the in-set column carries accepted_values with the exact value_set.
    AC1.7: a plain column carries no accepted_values."""
    umf = _umf(AV_FIXTURES / "lob_table.umf.yaml")
    files = generate_dbt_project(umf.model_dump(exclude_none=True))
    models = _model_by_name(files["models/schema.yml"])
    model = models["lob_table"]

    av = _accepted_values_args(_column_tests(model, "lob"))
    assert av == [{"values": ["MD", "MP", "ME"]}]

    # AC1.7: record_id / note have no accepted_values.
    assert _accepted_values_args(_column_tests(model, "record_id")) == []
    assert _accepted_values_args(_column_tests(model, "note")) == []


def test_schema_tests_accepted_values_on_dag_gold() -> None:
    """AC1.6: accepted_values is also emitted on a gold model column (DAG path)."""
    parent = _umf(FK_FIXTURES / "parent.umf.yaml")
    child = _umf(FK_FIXTURES / "child.umf.yaml")
    ce = _umf(FK_FIXTURES / "child_enriched.umf.yaml")
    # Attach an in-set expectation to the gold table's parent_id column.
    data = ce.model_dump(exclude_none=True)
    data["expectations"] = {
        "expectations": [
            {
                "type": "expect_column_values_to_be_in_set",
                "kwargs": {"column": "parent_id", "value_set": [1, 2, 3]},
                "meta": {"stage": "ingested"},
            }
        ]
    }
    ce2 = UMF(**data)
    files = generate_dbt_dag_project([parent, child, ce2])
    models = _model_by_name(files["models/schema.yml"])
    gold = models["gold_child_enriched"]
    tests = _column_tests(gold, "parent_id")
    # Both the relationships AND the accepted_values land on parent_id.
    assert _relationship_args(tests) == [
        {"to": "ref('ingested_parent')", "field": "parent_id"}
    ]
    # AC1.6 type fidelity: an INTEGER value_set [1, 2, 3] round-trips as numbers,
    # NOT coerced to the strings ["1", "2", "3"].
    assert _accepted_values_args(tests) == [{"values": [1, 2, 3]}]
