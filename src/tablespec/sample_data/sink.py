"""Unity Catalog SQL port and adapters; no credential handling in tablespec."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math
import re
import time
from typing import Any, Protocol
from uuid import uuid4

from tablespec.schemas.generators import generate_sql_ddl

from .streaming import GeneratedDataset


class SQLSink(Protocol):
    """Minimal injectable statement execution port."""

    def execute(self, statement: str) -> None:
        """Execute synchronously or raise on unsuccessful completion."""
        ...


def identifier(value: str) -> str:
    """Accept conservative UC identifiers, then quote them."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid Unity Catalog identifier: {value}")
    return f"`{value}`"


def target_namespace(target: str) -> str:
    """Require explicit UC catalog.schema and forbid Hive metastore."""
    parts = target.split(".")
    if len(parts) != 2 or parts[0].lower() == "hive_metastore":
        raise ValueError("Target must be Unity Catalog catalog.schema")
    return ".".join(identifier(part) for part in parts)


def literal(value: Any) -> str:
    """Render typed fabricated values without SQL string escaping ambiguity."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        if not math.isfinite(float(value)):
            raise ValueError("Non-finite numeric value")
        return str(value)
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    if isinstance(value, str):
        return f"decode(unhex('{value.encode('utf-8').hex()}'), 'UTF-8')"
    raise ValueError(f"Unsupported SQL literal type {type(value).__name__}")


def comment_literal(value: str) -> str:
    """Escape a Spark SQL comment literal, including backslashes."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def delta_ddl(spec: dict[str, Any], name: str) -> str:
    """Use the shared UMF DDL generator with a qualified Delta table name."""
    data = {
        **spec,
        "table_name": name,
        "relationships": {},
        "description": None,
        "canonical_name": name,
        "metadata": {},
    }
    columns = []
    for col in spec["columns"]:
        dtype = col["data_type"].upper()
        if not re.fullmatch(r"[A-Z]+", dtype):
            raise ValueError(f"Unsupported DDL type {dtype}")
        if dtype in ("TEXT", "CHAR"):
            dtype = "STRING"
        if dtype == "DATETIME":
            dtype = "TIMESTAMP"
        columns.append(
            {
                **col,
                "name": identifier(col["name"]),
                "data_type": dtype,
                "description": None,
            }
        )
    data["columns"] = columns
    lines = generate_sql_ddl(data).splitlines()
    for index, line in enumerate(lines):
        for col in spec["columns"]:
            if line.startswith("    " + identifier(col["name"]) + " ") and col.get(
                "description"
            ):
                trailing = "," if line.endswith(",") else ""
                lines[index] = (
                    line.removesuffix(",")
                    + " COMMENT "
                    + comment_literal(col["description"])
                    + trailing
                )
    ddl = "\n".join(lines).removesuffix(";") + "\nUSING DELTA"
    if spec.get("description"):
        ddl += "\nCOMMENT " + comment_literal(spec["description"])
    return ddl + ";"


@dataclass
class SparkSQLSink:
    """Execute on an existing Spark session supplied by the caller."""

    spark: Any

    def execute(self, statement: str) -> None:
        """Await Spark SQL completion."""
        self.spark.sql(statement).collect()


class WarehouseSQLSink:
    """Statement Execution adapter using an SDK auth profile, never secrets."""

    def __init__(
        self,
        warehouse_id: str,
        profile: str,
        client: Any = None,
        timeout_seconds: float = 300,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not warehouse_id or not profile:
            raise ValueError("warehouse_id and auth profile are required")
        if client is None:
            try:
                from databricks.sdk import WorkspaceClient
            except ImportError as exc:
                raise ImportError(
                    "Install tablespec[databricks] for warehouse loading"
                ) from exc
            client = WorkspaceClient(profile=profile)
        self.client = client
        self.warehouse_id = warehouse_id
        self.timeout_seconds = timeout_seconds
        self.sleep = sleep

    def execute(self, statement: str) -> None:
        """Poll through completion, cancel on timeout, and propagate failures."""
        response = self.client.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=statement, wait_timeout="10s"
        )
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            state = getattr(getattr(response, "status", None), "state", None)
            state = getattr(state, "value", state)
            if state == "SUCCEEDED":
                return
            if state not in ("PENDING", "RUNNING"):
                # Avoid copying remote errors, which can contain environment details.
                raise RuntimeError(f"Warehouse statement ended in {state}")
            if time.monotonic() >= deadline:
                self.client.statement_execution.cancel_execution(response.statement_id)
                raise TimeoutError("Warehouse statement timed out")
            self.sleep(1)
            response = self.client.statement_execution.get_statement(
                response.statement_id
            )


def load_dataset(
    dataset: GeneratedDataset,
    target: str,
    sink: SQLSink | None = None,
    *,
    dry_run: bool = False,
    drop_existing: bool = False,
    batch_size: int = 500,
    max_statement_bytes: int = 1_000_000,
) -> list[str]:
    """Stage bounded batches, then atomically overwrite each target's data.

    Publication is per table, not a cross-table transaction. A failed batch
    leaves that target untouched; a rerun regenerates/replaces the same data.
    Staging table names are unique to this invocation and cleaned in finally.
    """
    namespace = target_namespace(target)
    if batch_size <= 0 or max_statement_bytes <= 0:
        raise ValueError("Batch limits must be positive")
    if set(dataset.report) != set(dataset.specs):
        raise ValueError("Dataset must pass generation verification before loading")
    ddls = [
        delta_ddl(spec, f"{namespace}.{identifier(name)}")
        for name, spec in dataset.specs.items()
    ]
    if dry_run:
        return [
            f"CREATE SCHEMA IF NOT EXISTS {namespace};",
            *[
                f"{ddl}\n-- rows: {dataset.counts[name]}"
                for name, ddl in zip(dataset.specs, ddls, strict=True)
            ],
        ]
    if sink is None:
        raise ValueError("A sink is required except for dry-run")
    sink.execute(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
    for name, ddl in zip(dataset.specs, ddls, strict=True):
        final = f"{namespace}.{identifier(name)}"
        stage = f"{namespace}.{identifier('_tablespec_stage_' + uuid4().hex)}"
        sink.execute(delta_ddl(dataset.specs[name], stage))
        try:
            cols = [
                c["name"]
                for c in dataset.specs[name]["columns"]
                if not c.get("internal")
            ]
            prefix = (
                f"INSERT INTO {stage} ({','.join(identifier(c) for c in cols)}) VALUES "
            )
            values: list[str] = []
            size = len(prefix.encode())
            for batch in dataset.batches(name, batch_size):
                for row in batch:
                    value = "(" + ",".join(literal(row[c]) for c in cols) + ")"
                    encoded = len(value.encode()) + 1
                    if len(prefix.encode()) + encoded > max_statement_bytes:
                        raise ValueError("A row exceeds the statement byte limit")
                    if values and (
                        size + encoded > max_statement_bytes
                        or len(values) >= batch_size
                    ):
                        sink.execute(prefix + ",".join(values))
                        values = []
                        size = len(prefix.encode())
                    values.append(value)
                    size += encoded
            if values:
                sink.execute(prefix + ",".join(values))
            if drop_existing:
                sink.execute(f"DROP TABLE IF EXISTS {final}")
            sink.execute(ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
            # Explicit column list rejects schema drift before overwriting.
            sink.execute(
                f"INSERT OVERWRITE TABLE {final} ({','.join(identifier(c) for c in cols)}) SELECT {','.join(identifier(c) for c in cols)} FROM {stage}"
            )

            sink.execute(
                f"COMMENT ON TABLE {final} IS {comment_literal(dataset.specs[name].get('description') or '')}"
            )
            for col in dataset.specs[name]["columns"]:
                if not col.get("internal"):
                    sink.execute(
                        f"ALTER TABLE {final} ALTER COLUMN {identifier(col['name'])} COMMENT {comment_literal(col.get('description') or '')}"
                    )
        finally:
            sink.execute(f"DROP TABLE IF EXISTS {stage}")
    return ddls
