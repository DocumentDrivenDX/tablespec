"""Tests for startup configuration validation (FEAT-034 DIAG-01..04).

The claims under test:

  DIAG-01  the compute and the metadata catalog/schema/volume are checked
           before the app presents a usable surface
  DIAG-02  every fault names the setting at fault and the fix
  DIAG-03  unset optional settings are reported as disabled, not missing
  DIAG-04  the resolved location is describable without reading source

Also covered: validation never raises, and it stops early rather than blocking
on a warehouse that is not running (the two-second startup budget).
"""

# @covers US-049-AC1
# @covers US-049-AC2
# @covers US-049-AC4
# @covers US-049-AC5

from __future__ import annotations

import pytest

from profiler.config import (
    ENV_METADATA_SCHEMA,
    ENV_OUTPUT_VOLUME,
    ENV_WAREHOUSE_ID,
    AppConfig,
)
from profiler.diagnostics import (
    ERROR,
    WARNING,
    ConfigFault,
    describe_environment,
    summarize,
    validate_config,
)
from profiler.provision import expected_columns

from test_provision import FakeExecutor  # noqa: E402  (sibling test module)


# ---------------------------------------------------------------------------
# Fakes


class FakeWarehouses:
    def __init__(self, state="RUNNING", raises=None):
        self._state = state
        self._raises = raises

    def get(self, id):  # noqa: A002 - matches the SDK's parameter name
        if self._raises:
            raise self._raises
        return type("WH", (), {"state": self._state})()


class FakeUsers:
    def me(self):
        return type("Me", (), {"user_name": "app-sp@example.invalid"})()


class FakeWorkspace:
    def __init__(self, state="RUNNING", raises=None):
        self.warehouses = FakeWarehouses(state, raises)
        self.current_user = FakeUsers()


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


def _healthy_executor() -> FakeExecutor:
    wanted = expected_columns("cat", "sch")
    return FakeExecutor(
        schemas={"sch"},
        volumes={"vol"},
        tables=set(wanted),
        columns={t: set(c) for t, c in wanted.items()},
    )


# ---------------------------------------------------------------------------
# Healthy configuration


class TestHealthy:
    def test_no_faults_when_everything_present(self):
        faults = validate_config(
            _config(), executor=_healthy_executor(), workspace=FakeWorkspace()
        )
        assert faults == []

    def test_mock_runtime_probes_nothing(self):
        """Mock addresses no real resources, so there is nothing to validate."""
        ex = FakeExecutor()
        faults = validate_config(_config(runtime="mock"), executor=ex)
        assert faults == []
        assert ex.executed == []


# ---------------------------------------------------------------------------
# Compute faults


class TestCompute:
    def test_missing_warehouse_is_named(self):
        faults = validate_config(
            _config(warehouse_id=None),
            executor=FakeExecutor(),
            workspace=FakeWorkspace(),
        )
        assert len(faults) == 1
        assert faults[0].setting == ENV_WAREHOUSE_ID
        assert faults[0].severity == ERROR

    def test_missing_warehouse_stops_further_checks(self):
        """With no compute there is nothing to query, so do not emit noise."""
        ex = FakeExecutor()
        validate_config(
            _config(warehouse_id=None), executor=ex, workspace=FakeWorkspace()
        )
        assert ex.executed == []

    def test_unreachable_warehouse_names_the_grant(self):
        ws = FakeWorkspace(raises=PermissionError("403 not authorized"))
        faults = validate_config(_config(), executor=FakeExecutor(), workspace=ws)
        assert len(faults) == 1
        assert faults[0].setting == ENV_WAREHOUSE_ID
        assert "CAN USE" in faults[0].remedy

    def test_stopped_warehouse_defers_rather_than_blocking(self):
        """A cold start would blow the startup budget, so report and move on."""
        ws = FakeWorkspace(state="STOPPED")
        ex = FakeExecutor()
        faults = validate_config(_config(), executor=ex, workspace=ws)
        assert len(faults) == 1
        assert faults[0].severity == WARNING
        assert "deferred" in faults[0].problem.lower()
        assert ex.executed == []


# ---------------------------------------------------------------------------
# Metadata home faults


class TestMetadataHome:
    def test_missing_schema_points_at_provisioning(self):
        ex = FakeExecutor()  # no schema
        faults = validate_config(_config(), executor=ex, workspace=FakeWorkspace())
        assert len(faults) == 1
        assert faults[0].setting == ENV_METADATA_SCHEMA
        assert "provision.py" in faults[0].remedy

    def test_missing_schema_suppresses_downstream_faults(self):
        """One actionable fault beats three describing the same cause."""
        faults = validate_config(
            _config(), executor=FakeExecutor(), workspace=FakeWorkspace()
        )
        assert len(faults) == 1

    def test_missing_volume_is_reported(self):
        wanted = expected_columns("cat", "sch")
        ex = FakeExecutor(
            schemas={"sch"},
            volumes=set(),
            tables=set(wanted),
            columns={t: set(c) for t, c in wanted.items()},
        )
        faults = validate_config(_config(), executor=ex, workspace=FakeWorkspace())
        assert any(f.setting == ENV_OUTPUT_VOLUME for f in faults)

    def test_missing_tables_are_listed(self):
        wanted = expected_columns("cat", "sch")
        present = set(wanted) - {"column_alerts"}
        ex = FakeExecutor(
            schemas={"sch"},
            volumes={"vol"},
            tables=present,
            columns={t: set(wanted[t]) for t in present},
        )
        faults = validate_config(_config(), executor=ex, workspace=FakeWorkspace())
        table_faults = [f for f in faults if "column_alerts" in f.problem]
        assert table_faults
        assert "provision.py" in table_faults[0].remedy

    def test_unreadable_catalog_names_use_catalog_grant(self):
        class Boom(FakeExecutor):
            def query(self, statement):
                raise PermissionError("PERMISSION_DENIED")

        faults = validate_config(_config(), executor=Boom(), workspace=FakeWorkspace())
        assert faults
        assert "USE CATALOG" in faults[0].remedy


# ---------------------------------------------------------------------------
# DIAG-02 — message shape


class TestFaultMessage:
    def test_message_names_setting_resource_and_fix(self):
        fault = ConfigFault(
            setting="PROFILER_METADATA_SCHEMA",
            resource="cat.sch",
            problem="It does not exist.",
            remedy="Run provisioning.",
        )
        msg = fault.message()
        assert "PROFILER_METADATA_SCHEMA" in msg
        assert "cat.sch" in msg
        assert "Run provisioning." in msg

    def test_summarize_orders_errors_before_warnings(self):
        warn = ConfigFault("A", "a", "p", "r", severity=WARNING)
        err = ConfigFault("B", "b", "p", "r", severity=ERROR)
        out = summarize([warn, err])
        assert out.index("B") < out.index("A")

    def test_summarize_empty(self):
        assert summarize([]) == ""


# ---------------------------------------------------------------------------
# DIAG-03 / DIAG-04 — environment description


class TestDescribeEnvironment:
    def test_reports_metadata_home_and_sources(self):
        cfg = AppConfig(
            metadata_catalog="cat",
            metadata_schema="sch",
            output_volume="vol",
            runtime="databricks",
            sources={"metadata_catalog": "deployment"},
        )
        rows = describe_environment(cfg)
        labels = {r[0]: (r[1], r[2]) for r in rows}
        assert labels["Metadata catalog"] == ("cat", "deployment")
        assert labels["Metadata schema"][0] == "sch"

    def test_unset_optionals_read_as_disabled_not_missing(self):
        cfg = AppConfig(
            metadata_catalog="cat",
            metadata_schema="sch",
            output_volume="vol",
            runtime="databricks",
        )
        labels = {r[0]: r[1] for r in describe_environment(cfg)}
        for optional in ("Genie space", "Dashboard link", "Spec volume"):
            assert "disabled" in labels[optional]

    def test_set_optionals_are_shown(self):
        cfg = AppConfig(
            metadata_catalog="cat",
            metadata_schema="sch",
            output_volume="vol",
            runtime="databricks",
            genie_space_id="space-1",
            sources={"genie_space_id": "deployment"},
        )
        labels = {r[0]: r[1] for r in describe_environment(cfg)}
        assert labels["Genie space"] == "space-1"


# ---------------------------------------------------------------------------
# Robustness


@pytest.mark.parametrize(
    "boom",
    [PermissionError("403"), RuntimeError("boom"), TimeoutError("slow")],
)
def test_validation_never_raises(boom):
    """A diagnostic that throws is worse than the fault it was checking for."""

    class Boom(FakeExecutor):
        def query(self, statement):
            raise boom

    faults = validate_config(_config(), executor=Boom(), workspace=FakeWorkspace())
    assert isinstance(faults, list)
    assert faults
