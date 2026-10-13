"""Whole-stack unit path for FR-23 (config → provision → startup validate).

Satisfies the e2e-framework slot for the Databricks App at the unit level:
one command path exercises resolve + provision + diagnostics without a live
workspace. Live deploy-and-drive remains operational evidence.
"""

# @covers US-047-AC2
# @covers US-047-AC6
# @covers US-048-AC5
# @covers US-049-AC3
# @covers US-049-AC6

from __future__ import annotations

from pathlib import Path

from profiler.config import resolve_config
from profiler.diagnostics import validate_config
from profiler.provision import ProvisionReport, provision


class _EmptyExecutor:
    """Empty environment: nothing exists yet."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def query(self, statement: str) -> list[list]:
        return []


def test_fr23_resolve_provision_validate_compose(tmp_path: Path) -> None:
    """Config resolve → idempotent provision → startup validation compose."""
    registry = tmp_path / "connections.yaml"
    registry.write_text("connections: []\n", encoding="utf-8")

    cfg = resolve_config(
        env={
            "PROFILER_METADATA_CATALOG": "stack_cat",
            "PROFILER_METADATA_SCHEMA": "stack_schema",
            "PROFILER_OUTPUT_VOLUME": "stack_vol",
            "DATABRICKS_WAREHOUSE_ID": "wh-stack",
            "PROFILER_RUNTIME": "mock",
        },
        registry_path=str(registry),
    )
    assert cfg.metadata_catalog == "stack_cat"
    assert cfg.source_of("metadata_catalog") == "deployment"

    empty = _EmptyExecutor()
    report = provision(cfg, executor=empty, grant_to=None)
    assert isinstance(report, ProvisionReport)
    assert report.changed is True
    assert empty.statements  # DDL issued on empty environment

    # Smoke: mock runtime validation is list-shaped and non-raising.
    faults = validate_config(cfg)
    assert isinstance(faults, list)
    assert faults == []  # mock runtime skips warehouse probes


def test_fr23_smoke_exit_zero_composition(tmp_path: Path) -> None:
    """CLI-equivalent smoke: resolve + provision + validate returns success."""
    from profiler.smoke import run_fr23_smoke

    code = run_fr23_smoke(
        env={
            "PROFILER_METADATA_CATALOG": "smoke_cat",
            "PROFILER_METADATA_SCHEMA": "smoke_schema",
            "PROFILER_OUTPUT_VOLUME": "smoke_vol",
            "PROFILER_RUNTIME": "mock",
        },
        registry_path=str(tmp_path / "missing.yaml"),
        executor=_EmptyExecutor(),
    )
    assert code == 0
