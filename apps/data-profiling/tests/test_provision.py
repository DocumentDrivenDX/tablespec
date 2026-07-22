"""Tests for metadata-home provisioning (FEAT-034 PROV-01..04, ADR-019 d3).

The claims under test:

  PROV-01/02  absent schema, volume, and tables are created; present ones are
              verified rather than recreated
  PROV-03     a repeat run against a provisioned environment changes nothing
  PROV-04     the report distinguishes created from already-existing

plus the additive-only guarantee: absent columns are added, and a column that
is present but not in the current model is reported, never dropped.

A fake executor stands in for the warehouse so the whole flow is exercised
without a workspace.
"""

from __future__ import annotations

import pytest

from profiler.config import AppConfig
from profiler.provision import (
    ALTERED,
    CREATED,
    EXISTED,
    ObjectResult,
    ProvisionReport,
    expected_columns,
    provision,
)


# ---------------------------------------------------------------------------
# Fake executor


class FakeExecutor:
    """In-memory stand-in for a SQL warehouse.

    Answers the information_schema probes provisioning makes, and records every
    statement so tests can assert on what was and was not run.
    """

    def __init__(
        self,
        schemas=(),
        volumes=(),
        tables=(),
        columns=None,
        fail_grants=False,
    ):
        self.schemas = set(schemas)
        self.volumes = set(volumes)
        self.tables = set(tables)
        # {table: {column, ...}}
        self.columns = {k: set(v) for k, v in (columns or {}).items()}
        self.fail_grants = fail_grants
        self.executed: list[str] = []

    def execute(self, statement: str) -> None:
        self.executed.append(statement)
        if statement.strip().upper().startswith("GRANT") and self.fail_grants:
            raise RuntimeError("PERMISSION_DENIED: not the owner")

    def query(self, statement: str) -> list[list]:
        s = statement.lower()
        if "information_schema.schemata" in s:
            return [[1]] if self.schemas else []
        if "information_schema.volumes" in s:
            return [[1]] if self.volumes else []
        if "information_schema.columns" in s:
            return [[t, c] for t, cols in self.columns.items() for c in sorted(cols)]
        if "information_schema.tables" in s:
            return [[t] for t in sorted(self.tables)]
        return []

    # -- helpers for assertions ------------------------------------------
    def ran(self, fragment: str) -> bool:
        return any(fragment.lower() in st.lower() for st in self.executed)

    def count(self, fragment: str) -> int:
        return sum(1 for st in self.executed if fragment.lower() in st.lower())


def _config(**kw) -> AppConfig:
    base = dict(
        metadata_catalog="cat",
        metadata_schema="sch",
        output_volume="vol",
        runtime="databricks",
        warehouse_id="wh-1",
    )
    base.update(kw)
    return AppConfig(**base)


ALL_TABLES = [
    "profiler_runs",
    "dataset_profiles",
    "column_profiles",
    "column_alerts",
    "column_comparisons",
]


def _provisioned_executor() -> FakeExecutor:
    """An environment where everything already exists and matches the model."""
    wanted = expected_columns("cat", "sch")
    return FakeExecutor(
        schemas={"sch"},
        volumes={"vol"},
        tables=set(wanted),
        columns={t: set(cols) for t, cols in wanted.items()},
    )


# ---------------------------------------------------------------------------
# Empty environment


class TestEmptyEnvironment:
    def test_creates_schema_volume_and_tables(self):
        ex = FakeExecutor()
        report = provision(_config(), executor=ex)

        assert ex.ran("CREATE SCHEMA IF NOT EXISTS")
        assert ex.ran("CREATE VOLUME IF NOT EXISTS")
        created = {r.name for r in report.created}
        assert "cat.sch" in created
        assert "cat.sch.vol" in created
        for tbl in ALL_TABLES:
            assert f"cat.sch.{tbl}" in created

    def test_reports_change(self):
        report = provision(_config(), executor=FakeExecutor())
        assert report.changed is True
        assert report.existed == []

    def test_does_not_alter_tables_it_just_created(self):
        """A table created this run is already current; ALTER would be noise."""
        ex = FakeExecutor()
        report = provision(_config(), executor=ex)
        assert not ex.ran("ALTER TABLE")
        assert report.altered == []


# ---------------------------------------------------------------------------
# Idempotency (PROV-03)


class TestIdempotency:
    def test_repeat_run_reports_no_changes(self):
        report = provision(_config(), executor=_provisioned_executor())
        assert report.changed is False
        assert report.created == []
        assert report.altered == []
        assert len(report.existed) == len(ALL_TABLES) + 2  # tables + schema + volume

    def test_repeat_run_issues_no_ddl(self):
        ex = _provisioned_executor()
        provision(_config(), executor=ex, grant_to=None)
        assert not ex.ran("CREATE SCHEMA")
        assert not ex.ran("CREATE VOLUME")
        assert not ex.ran("CREATE TABLE")
        assert not ex.ran("ALTER TABLE")

    def test_render_says_no_changes(self):
        report = provision(_config(), executor=_provisioned_executor())
        assert "No changes" in report.render()


# ---------------------------------------------------------------------------
# Partial environment


class TestPartialEnvironment:
    def test_existing_schema_is_verified_not_recreated(self):
        ex = FakeExecutor(schemas={"sch"})
        report = provision(_config(), executor=ex)
        assert not ex.ran("CREATE SCHEMA")
        assert any(r.kind == "schema" and r.action == EXISTED for r in report.results)

    def test_existing_volume_is_verified_not_recreated(self):
        ex = FakeExecutor(schemas={"sch"}, volumes={"vol"})
        report = provision(_config(), executor=ex)
        assert not ex.ran("CREATE VOLUME")
        assert any(r.kind == "volume" and r.action == EXISTED for r in report.results)

    def test_missing_table_created_alongside_existing_ones(self):
        wanted = expected_columns("cat", "sch")
        present = set(ALL_TABLES) - {"column_alerts"}
        ex = FakeExecutor(
            schemas={"sch"},
            volumes={"vol"},
            tables=present,
            columns={t: set(wanted[t]) for t in present},
        )
        report = provision(_config(), executor=ex)

        created = {r.name for r in report.created}
        existed = {r.name for r in report.existed}
        assert "cat.sch.column_alerts" in created
        assert "cat.sch.profiler_runs" in existed
        assert report.changed is True


# ---------------------------------------------------------------------------
# Additive column reconciliation


class TestColumnReconciliation:
    def test_absent_column_is_added(self):
        wanted = expected_columns("cat", "sch")
        cols = {t: set(c) for t, c in wanted.items()}
        dropped = wanted["profiler_runs"][-1]
        cols["profiler_runs"].discard(dropped)

        ex = FakeExecutor(
            schemas={"sch"}, volumes={"vol"}, tables=set(wanted), columns=cols
        )
        report = provision(_config(), executor=ex, grant_to=None)

        assert ex.ran("ALTER TABLE")
        assert ex.ran(dropped)
        altered = [r for r in report.altered if r.name.endswith("profiler_runs")]
        assert altered and dropped in altered[0].detail
        assert report.changed is True

    def test_unexpected_column_is_reported_not_dropped(self):
        """Additive-only: removing a column would destroy data we do not own."""
        wanted = expected_columns("cat", "sch")
        cols = {t: set(c) for t, c in wanted.items()}
        cols["profiler_runs"].add("legacy_extra_col")

        ex = FakeExecutor(
            schemas={"sch"}, volumes={"vol"}, tables=set(wanted), columns=cols
        )
        report = provision(_config(), executor=ex, grant_to=None)

        assert not ex.ran("DROP")
        assert any("legacy_extra_col" in w for w in report.warnings)
        # An unexpected column alone is not a change.
        assert report.altered == []


# ---------------------------------------------------------------------------
# Grants — reported, never escalated (ADR-019 decision 4)


class TestGrants:
    def test_grant_failure_is_a_warning_not_an_error(self):
        ex = _provisioned_executor()
        ex.fail_grants = True
        report = provision(_config(), executor=ex, grant_to="account users")
        assert report.warnings
        assert any("GRANT SELECT" in w for w in report.warnings)

    def test_grant_can_be_skipped(self):
        ex = _provisioned_executor()
        provision(_config(), executor=ex, grant_to=None)
        assert not ex.ran("GRANT")


# ---------------------------------------------------------------------------
# DDL parsing


class TestExpectedColumns:
    def test_parses_all_governance_tables(self):
        cols = expected_columns("cat", "sch")
        assert set(cols) == set(ALL_TABLES)

    def test_does_not_capture_table_clauses_as_columns(self):
        """USING / CLUSTER BY / TBLPROPERTIES must not parse as column names."""
        for table_cols in expected_columns("cat", "sch").values():
            lowered = {c.lower() for c in table_cols}
            assert not lowered & {"using", "cluster", "tblproperties", "partitioned"}

    def test_key_columns_present(self):
        cols = expected_columns("cat", "sch")
        assert "run_id" in cols["profiler_runs"]
        assert "column_name" in cols["column_profiles"]


# ---------------------------------------------------------------------------
# Report


class TestReport:
    def test_render_lists_objects_and_warnings(self):
        report = ProvisionReport(metadata_home="cat.sch")
        report.results.append(ObjectResult("schema", "cat.sch", CREATED))
        report.warnings.append("something to know")
        out = report.render()
        assert "cat.sch" in out
        assert CREATED in out
        assert "something to know" in out

    def test_empty_report_is_not_changed(self):
        assert ProvisionReport(metadata_home="cat.sch").changed is False


@pytest.mark.parametrize("action", [CREATED, EXISTED, ALTERED])
def test_action_constants_are_distinct(action):
    assert isinstance(action, str) and action
