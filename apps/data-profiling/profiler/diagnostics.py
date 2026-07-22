"""Startup validation of the resolved configuration (FEAT-034 DIAG-01/02).

ADR-019 decision 4: the app checks its configuration before presenting a usable
surface, and when the running identity lacks a privilege it names the resource
and the grant an administrator must apply. It never attempts to acquire
privileges the deploying identity does not hold.

Every fault carries the setting at fault and the remedy, so an operator reads a
sentence instead of a stack trace (DIAG-02).

Ordering matters for the startup budget. The checks run cheapest-first and stop
as soon as a fault makes the rest unanswerable: with no warehouse configured
there is nothing to query, and with a warehouse that is stopped the metadata
probes would block on a cold start rather than return an answer. The
non-functional budget is two seconds added to app start, so a stopped warehouse
is reported as a deferred check rather than waited on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .config import (
    ENV_METADATA_CATALOG,
    ENV_METADATA_SCHEMA,
    ENV_OUTPUT_VOLUME,
    ENV_WAREHOUSE_ID,
    AppConfig,
)
from .provision import SqlExecutor, expected_columns

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class ConfigFault:
    """One actionable configuration problem."""

    setting: str  # the declared input at fault
    resource: str  # the resource it addresses
    problem: str  # what is wrong
    remedy: str  # what to do about it
    severity: str = ERROR

    def message(self) -> str:
        """One message naming the setting, the resource, and the fix (DIAG-02)."""
        return f"{self.setting} → {self.resource}: {self.problem} Fix: {self.remedy}"


def _identity(workspace) -> str:
    """Best-effort name of the identity the app runs as, for grant text."""
    try:
        me = workspace.current_user.me()
        return (
            getattr(me, "user_name", None)
            or getattr(me, "display_name", None)
            or "the app's service principal"
        )
    except Exception:  # noqa: BLE001
        return "the app's service principal"


def validate_config(
    config: AppConfig,
    executor: Optional[SqlExecutor] = None,
    workspace=None,
) -> list[ConfigFault]:
    """Check that the resolved configuration is usable (DIAG-01).

    Returns faults in the order they were detected; an empty list means the
    configuration is usable. Never raises: a diagnostic that throws is worse
    than the fault it was checking for.
    """
    if not config.is_databricks:
        # Mock runtime addresses no real resources, so there is nothing to
        # probe and no fault to report.
        return []

    faults: list[ConfigFault] = []

    # --- compute ----------------------------------------------------------
    if not config.warehouse_id:
        faults.append(
            ConfigFault(
                setting=ENV_WAREHOUSE_ID,
                resource="(unset)",
                problem="No SQL warehouse is configured, so no metadata query can run.",
                remedy=f"Set {ENV_WAREHOUSE_ID} in the deployment manifest.",
            )
        )
        # Everything below needs a warehouse; stop rather than emit noise.
        return faults

    if workspace is None:
        try:
            from .catalog import _workspace_client

            workspace = _workspace_client()
        except Exception as exc:  # noqa: BLE001
            faults.append(
                ConfigFault(
                    setting=ENV_WAREHOUSE_ID,
                    resource=config.warehouse_id,
                    problem=f"Could not create a workspace client ({exc}).",
                    remedy="Verify the app's credentials and workspace host.",
                )
            )
            return faults

    warehouse_running = False
    try:
        wh = workspace.warehouses.get(id=config.warehouse_id)
        warehouse_running = "RUNNING" in str(getattr(wh, "state", "")).upper()
    except Exception as exc:  # noqa: BLE001
        who = _identity(workspace)
        faults.append(
            ConfigFault(
                setting=ENV_WAREHOUSE_ID,
                resource=config.warehouse_id,
                problem=f"The warehouse is not reachable ({exc}).",
                remedy=(
                    f"Grant {who} CAN USE on the warehouse, or point "
                    f"{ENV_WAREHOUSE_ID} at one it can use."
                ),
            )
        )
        return faults

    if not warehouse_running:
        # Probing metadata now would block on a cold start and blow the
        # two-second startup budget, so defer rather than wait.
        faults.append(
            ConfigFault(
                setting=ENV_WAREHOUSE_ID,
                resource=config.warehouse_id,
                problem="The warehouse is not running, so metadata checks were deferred.",
                remedy="Start the warehouse (Initialize Compute in the sidebar).",
                severity=WARNING,
            )
        )
        return faults

    # --- metadata home ----------------------------------------------------
    if executor is None:
        from .provision import DatabricksExecutor

        executor = DatabricksExecutor(config.warehouse_id)

    faults.extend(_check_metadata_home(config, executor, workspace))
    return faults


def _check_metadata_home(
    config: AppConfig, executor: SqlExecutor, workspace
) -> list[ConfigFault]:
    """Probe catalog, schema, volume, and governance tables."""
    faults: list[ConfigFault] = []
    who = _identity(workspace)
    catalog = config.metadata_catalog
    schema = config.metadata_schema

    from .provision import (
        _existing_tables,
        _schema_exists,
        _volume_exists,
    )

    # The catalog probe doubles as the readability check: a missing USE CATALOG
    # grant fails the same query a missing catalog does, so the remedy names
    # both possibilities rather than guessing.
    try:
        schema_present = _schema_exists(executor, catalog, schema)
    except Exception as exc:  # noqa: BLE001
        faults.append(
            ConfigFault(
                setting=ENV_METADATA_CATALOG,
                resource=catalog,
                problem=f"The catalog could not be read ({exc}).",
                remedy=(
                    f"Confirm the catalog exists and grant {who} USE CATALOG on it."
                ),
            )
        )
        return faults

    if not schema_present:
        faults.append(
            ConfigFault(
                setting=ENV_METADATA_SCHEMA,
                resource=config.metadata_fqn,
                problem="The metadata schema does not exist.",
                remedy=(
                    "Run `python scripts/provision.py` against this environment, "
                    f"or grant {who} USE SCHEMA if it exists but is not visible."
                ),
            )
        )
        # Volume and tables live inside the schema; one fault is enough.
        return faults

    try:
        if not _volume_exists(executor, catalog, schema, config.output_volume):
            faults.append(
                ConfigFault(
                    setting=ENV_OUTPUT_VOLUME,
                    resource=f"{config.metadata_fqn}.{config.output_volume}",
                    problem="The output volume does not exist, so run artifacts cannot be written.",
                    remedy="Run `python scripts/provision.py` to create it.",
                )
            )
    except Exception as exc:  # noqa: BLE001
        faults.append(
            ConfigFault(
                setting=ENV_OUTPUT_VOLUME,
                resource=f"{config.metadata_fqn}.{config.output_volume}",
                problem=f"The output volume could not be read ({exc}).",
                remedy=f"Grant {who} READ VOLUME on it.",
                severity=WARNING,
            )
        )

    try:
        present = _existing_tables(executor, catalog, schema)
    except Exception as exc:  # noqa: BLE001
        faults.append(
            ConfigFault(
                setting=ENV_METADATA_SCHEMA,
                resource=config.metadata_fqn,
                problem=f"Governance tables could not be listed ({exc}).",
                remedy=f"Grant {who} USE SCHEMA and SELECT on the schema.",
                severity=WARNING,
            )
        )
        return faults

    missing = sorted(set(expected_columns(catalog, schema)) - present)
    if missing:
        faults.append(
            ConfigFault(
                setting=ENV_METADATA_SCHEMA,
                resource=config.metadata_fqn,
                problem=f"Governance table(s) missing: {', '.join(missing)}.",
                remedy="Run `python scripts/provision.py` to create them.",
            )
        )

    return faults


# ---------------------------------------------------------------------------
# Operator-facing summary (DIAG-04)


def describe_environment(config: AppConfig) -> list[tuple[str, str, str]]:
    """Rows of (label, value, source) describing where this deployment points.

    Optional settings that are unset are reported as disabled rather than
    omitted, so an operator can tell "off" from "missing" (DIAG-03).
    """
    rows = [
        (
            "Metadata catalog",
            config.metadata_catalog,
            config.source_of("metadata_catalog"),
        ),
        (
            "Metadata schema",
            config.metadata_schema,
            config.source_of("metadata_schema"),
        ),
        ("Output volume", config.output_volume_path, config.source_of("output_volume")),
        ("Runtime", config.runtime, config.source_of("runtime")),
        (
            "SQL warehouse",
            config.warehouse_id or "(not set)",
            config.source_of("warehouse_id"),
        ),
    ]
    for label, value, key in (
        ("Genie space", config.genie_space_id, "genie_space_id"),
        ("Dashboard link", config.dashboard_url, "dashboard_url"),
        ("Spec volume", config.spec_volume, "spec_volume"),
    ):
        rows.append(
            (
                label,
                value or "(disabled — not set)",
                config.source_of(key) if value else "—",
            )
        )
    return rows


def summarize(faults: Sequence[ConfigFault]) -> str:
    """One block of text listing every fault, most severe first."""
    if not faults:
        return ""
    ordered = sorted(faults, key=lambda f: 0 if f.severity == ERROR else 1)
    return "\n\n".join(f.message() for f in ordered)
