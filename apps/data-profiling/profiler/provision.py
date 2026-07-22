"""Provision the declared metadata home (FEAT-034 PROV-01..04, ADR-019).

ADR-019 decision 3: provisioning is an explicit, idempotent, additive
deployment step — not lazy creation on first write. It creates or verifies the
schema, the output volume, and the governance tables, and reports what it
created versus what already existed.

Additive only. Absent tables are created and absent columns are added; nothing
is dropped or rewritten. A column present in the target but not in the current
model is reported as unexpected rather than removed, because dropping it would
destroy data provisioning does not own (ADR-019, "additive-only migration"
risk).

The SQL runs through an injected executor so the whole flow is testable without
a workspace; `DatabricksExecutor` is the real one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

from .config import AppConfig
from .delta_repo import _ddl


# ---------------------------------------------------------------------------
# Executor seam


class SqlExecutor(Protocol):
    """Minimal SQL surface provisioning needs."""

    def execute(self, statement: str) -> None:
        """Run a statement, raising on failure."""

    def query(self, statement: str) -> list[list]:
        """Run a query, returning its rows."""


class DatabricksExecutor:
    """Real executor, backed by the Statement Execution API."""

    def __init__(self, warehouse_id: Optional[str] = None) -> None:
        self._warehouse_id = warehouse_id

    def execute(self, statement: str) -> None:
        from .delta_repo import _exec_sql

        _exec_sql(statement)

    def query(self, statement: str) -> list[list]:
        import os
        import time

        from .catalog import _workspace_client

        w = _workspace_client()
        wid = self._warehouse_id or os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
        result = w.statement_execution.execute_statement(
            warehouse_id=wid, statement=statement, wait_timeout="50s"
        )
        deadline = time.time() + 300
        while True:
            state = str(result.status.state).upper() if result.status else "UNKNOWN"
            if "SUCCEEDED" in state:
                data = (result.result.data_array if result.result else None) or []
                return [list(r) for r in data]
            if any(s in state for s in ("FAILED", "CANCELLED", "CLOSED")):
                err = (
                    result.status.error.message
                    if (result.status and result.status.error)
                    else state
                )
                raise RuntimeError(f"SQL failed ({state}): {err}")
            if time.time() > deadline:
                raise TimeoutError(f"SQL still {state} after 5 minutes")
            time.sleep(2)
            result = w.statement_execution.get_statement(result.statement_id)


# ---------------------------------------------------------------------------
# Report types

CREATED = "created"
EXISTED = "existed"
ALTERED = "altered"


@dataclass(frozen=True)
class ObjectResult:
    kind: str  # "schema" | "volume" | "table"
    name: str
    action: str  # CREATED | EXISTED | ALTERED
    detail: str = ""


@dataclass
class ProvisionReport:
    """What provisioning found and what it changed (PROV-04)."""

    metadata_home: str
    results: list[ObjectResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def created(self) -> list[ObjectResult]:
        return [r for r in self.results if r.action == CREATED]

    @property
    def existed(self) -> list[ObjectResult]:
        return [r for r in self.results if r.action == EXISTED]

    @property
    def altered(self) -> list[ObjectResult]:
        return [r for r in self.results if r.action == ALTERED]

    @property
    def changed(self) -> bool:
        """True when this run modified anything.

        A repeat run against a provisioned environment must report False —
        that is the idempotency claim in PROV-03.
        """
        return bool(self.created or self.altered)

    def render(self) -> str:
        lines = [f"Metadata home: {self.metadata_home}", ""]
        for r in self.results:
            suffix = f" — {r.detail}" if r.detail else ""
            lines.append(f"  [{r.action:>7}] {r.kind:<6} {r.name}{suffix}")
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"  - {w}" for w in self.warnings)
        lines.append("")
        lines.append(
            "No changes — already provisioned."
            if not self.changed
            else f"Changed: {len(self.created)} created, {len(self.altered)} altered."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Expected-column extraction
#
# The governance DDL in delta_repo is the source of truth for the model. Rather
# than restating it here (two copies drift), the expected columns are read back
# out of those generated statements. The format is our own and stable; if it
# ever stops parsing, provisioning reports that it could not verify columns
# instead of silently skipping the check.

_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+.*?\.`?(?P<table>\w+)`?\s*\((?P<body>.*?)\)\s*(?:USING|PARTITIONED|CLUSTER|TBLPROPERTIES|$)",
    re.IGNORECASE | re.DOTALL,
)
_COLUMN_RE = re.compile(r"^\s*`?(?P<name>\w+)`?\s+(?P<type>[A-Za-z]+(?:\s*\([^)]*\))?)")

# Line-leading keywords that introduce a table constraint rather than a column.
_NOT_A_COLUMN = ("primary", "foreign", "constraint", "unique", "check")


def expected_columns(catalog: str, schema: str) -> dict[str, list[str]]:
    """Map governance table name -> ordered column names, parsed from the DDL."""
    out: dict[str, list[str]] = {}
    for stmt in _ddl(catalog, schema):
        m = _CREATE_RE.search(stmt)
        if not m:
            continue
        table = m.group("table")
        cols: list[str] = []
        for raw in m.group("body").split("\n"):
            line = raw.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            if line.split(" ", 1)[0].lower() in _NOT_A_COLUMN:
                continue
            cm = _COLUMN_RE.match(line)
            if cm:
                cols.append(cm.group("name"))
        if cols:
            out[table] = cols
    return out


def _column_types(catalog: str, schema: str) -> dict[tuple[str, str], str]:
    """Map (table, column) -> declared SQL type, parsed from the DDL."""
    out: dict[tuple[str, str], str] = {}
    for stmt in _ddl(catalog, schema):
        m = _CREATE_RE.search(stmt)
        if not m:
            continue
        table = m.group("table")
        for raw in m.group("body").split("\n"):
            line = raw.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            if line.split(" ", 1)[0].lower() in _NOT_A_COLUMN:
                continue
            cm = _COLUMN_RE.match(line)
            if cm:
                out[(table, cm.group("name"))] = cm.group("type").strip()
    return out


# ---------------------------------------------------------------------------
# Existence probes


def _quote(value: str) -> str:
    """Single-quote a SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def _schema_exists(ex: SqlExecutor, catalog: str, schema: str) -> bool:
    rows = ex.query(
        f"SELECT 1 FROM `{catalog}`.information_schema.schemata "
        f"WHERE schema_name = {_quote(schema)} LIMIT 1"
    )
    return bool(rows)


def _volume_exists(ex: SqlExecutor, catalog: str, schema: str, volume: str) -> bool:
    rows = ex.query(
        f"SELECT 1 FROM `{catalog}`.information_schema.volumes "
        f"WHERE volume_schema = {_quote(schema)} "
        f"AND volume_name = {_quote(volume)} LIMIT 1"
    )
    return bool(rows)


def _existing_tables(ex: SqlExecutor, catalog: str, schema: str) -> set[str]:
    rows = ex.query(
        f"SELECT table_name FROM `{catalog}`.information_schema.tables "
        f"WHERE table_schema = {_quote(schema)}"
    )
    return {str(r[0]) for r in rows if r}


def _existing_columns(
    ex: SqlExecutor, catalog: str, schema: str
) -> dict[str, set[str]]:
    rows = ex.query(
        f"SELECT table_name, column_name FROM `{catalog}`.information_schema.columns "
        f"WHERE table_schema = {_quote(schema)}"
    )
    out: dict[str, set[str]] = {}
    for r in rows:
        if len(r) >= 2:
            out.setdefault(str(r[0]), set()).add(str(r[1]))
    return out


# ---------------------------------------------------------------------------
# Provisioning


def provision(
    config: AppConfig,
    executor: Optional[SqlExecutor] = None,
    grant_to: Optional[str] = "account users",
) -> ProvisionReport:
    """Create or verify the declared metadata home. Idempotent and additive.

    `grant_to` receives SELECT on the governance tables. A grant failure is a
    warning, not an error: per ADR-019 the app reports the grant an admin must
    apply rather than escalating its own privileges.
    """
    ex = executor or DatabricksExecutor(config.warehouse_id)
    catalog = config.metadata_catalog
    schema = config.metadata_schema
    report = ProvisionReport(metadata_home=config.metadata_fqn)

    # --- schema -----------------------------------------------------------
    if _schema_exists(ex, catalog, schema):
        report.results.append(ObjectResult("schema", config.metadata_fqn, EXISTED))
    else:
        ex.execute(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")
        report.results.append(ObjectResult("schema", config.metadata_fqn, CREATED))

    # --- volume -----------------------------------------------------------
    volume_fqn = f"{config.metadata_fqn}.{config.output_volume}"
    if _volume_exists(ex, catalog, schema, config.output_volume):
        report.results.append(ObjectResult("volume", volume_fqn, EXISTED))
    else:
        ex.execute(
            f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{config.output_volume}`"
        )
        report.results.append(ObjectResult("volume", volume_fqn, CREATED))

    # --- governance tables ------------------------------------------------
    wanted = expected_columns(catalog, schema)
    if not wanted:
        report.warnings.append(
            "Could not parse governance DDL; table columns were not verified."
        )

    present = _existing_tables(ex, catalog, schema)
    for stmt in _ddl(catalog, schema):
        m = _CREATE_RE.search(stmt)
        table = m.group("table") if m else None
        if table is None:
            ex.execute(stmt)
            continue
        if table in present:
            report.results.append(
                ObjectResult("table", f"{config.metadata_fqn}.{table}", EXISTED)
            )
        else:
            ex.execute(stmt)
            report.results.append(
                ObjectResult("table", f"{config.metadata_fqn}.{table}", CREATED)
            )

    # --- additive column reconciliation ----------------------------------
    if wanted:
        _reconcile_columns(ex, config, wanted, present, report)

    # --- grants -----------------------------------------------------------
    if grant_to:
        for table in wanted or {}:
            try:
                ex.execute(
                    f"GRANT SELECT ON TABLE `{catalog}`.`{schema}`.`{table}` "
                    f"TO `{grant_to}`"
                )
            except Exception as exc:  # noqa: BLE001
                report.warnings.append(
                    f"GRANT SELECT on {config.metadata_fqn}.{table} to `{grant_to}` "
                    f"failed ({exc}). An administrator can run: "
                    f"GRANT SELECT ON TABLE {config.metadata_fqn}.{table} "
                    f"TO `{grant_to}`;"
                )

    return report


def _reconcile_columns(
    ex: SqlExecutor,
    config: AppConfig,
    wanted: dict[str, list[str]],
    tables_that_existed: Sequence[str] | set[str],
    report: ProvisionReport,
) -> None:
    """Add absent columns to pre-existing tables; report unexpected ones."""
    catalog = config.metadata_catalog
    schema = config.metadata_schema
    types = _column_types(catalog, schema)
    actual = _existing_columns(ex, catalog, schema)

    for table, cols in wanted.items():
        # A table this run created is already at the current model.
        if table not in tables_that_existed:
            continue
        have = actual.get(table, set())
        if not have:
            continue

        missing = [c for c in cols if c not in have]
        if missing:
            adds = ", ".join(
                f"`{c}` {types.get((table, c), 'STRING')}" for c in missing
            )
            ex.execute(
                f"ALTER TABLE `{catalog}`.`{schema}`.`{table}` ADD COLUMNS ({adds})"
            )
            report.results.append(
                ObjectResult(
                    "table",
                    f"{config.metadata_fqn}.{table}",
                    ALTERED,
                    f"added {', '.join(missing)}",
                )
            )

        unexpected = sorted(have - set(cols))
        if unexpected:
            report.warnings.append(
                f"{config.metadata_fqn}.{table} has column(s) not in the current "
                f"model: {', '.join(unexpected)}. Left in place — removing a column "
                f"destroys data and is a deliberate migration."
            )
