"""Parse the runtime-relevant schema out of the COMPILED artifacts.

The runtime BACKBONE must consume only persisted compiled artifacts, never the
source UMF. The compiled ``ingest/<t>.ingest.sql`` (the ``generate_ingest_sql``
output) already carries everything the runtime ingest needs, in two CREATE TABLE
blocks:

  1. the RAW landing table -- every business column ``STRING`` plus the
     ``_source_file`` / ``_load_ts`` provenance columns. This pins the raw-load
     column order + the all-STRING raw schema.
  2. the TYPED target table -- each business column at its cast target type,
     including ``DECIMAL(p,s)``. This pins the typed projection column order, the
     typed table name, and the decimal SCALE map used by the canonicalizer.

This module parses those blocks into a small :class:`CompiledSchema` so the
backbone engines can build the raw-load relation, the typed projection, the table
names, and the decimal-scale map WITHOUT re-reading or re-parsing the UMF
snapshot (which is a non-load-bearing audit artifact per
``manifest.py``). Parsing the committed SQL keeps the runtime anchored to the
compiled output the way production would consume it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A column line inside a CREATE TABLE body, e.g. ``    claim_id INT NOT NULL`` or
# ``    amount   DECIMAL(12,4)``. Group 1 = name, group 2 = the type token (up to
# the trailing NOT NULL / comma).
_COL_LINE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)(?:\s+NOT\s+NULL)?\s*,?\s*$",
)
_DECIMAL = re.compile(r"DECIMAL\s*\(\s*\d+\s*,\s*(\d+)\s*\)", re.IGNORECASE)

# Provenance columns appended to the raw landing table (not business columns).
_META_COLUMNS = {"_source_file", "_load_ts"}


@dataclass(frozen=True)
class CompiledSchema:
    """Runtime schema derived from a compiled ``ingest.sql`` artifact.

    Attributes:
        raw_table: the raw landing table name (``raw_<t>``).
        ingested_table: the typed target table name (``ingested_<t>``).
        columns: business column names in UMF order (the typed-projection order;
            identical to the raw-landing business-column order).
        decimal_scales: ``{column: scale}`` for every DECIMAL typed column -- the
            scale map the canonicalizer renders with (compiled, not UMF-derived).
    """

    raw_table: str
    ingested_table: str
    columns: list[str]
    decimal_scales: dict[str, int | None]


def _create_table_body(sql: str, table_name: str) -> list[str]:
    """Return the column-definition lines inside ``CREATE TABLE ... ( <body> )``.

    Locates the ``CREATE TABLE [IF NOT EXISTS] <table_name> (`` header and returns
    the lines between its opening ``(`` and the matching ``)``.
    """
    pattern = re.compile(
        rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(table_name)}\s*\(",
        re.IGNORECASE,
    )
    m = pattern.search(sql)
    if m is None:  # pragma: no cover - compiled ingest always defines both tables
        raise ValueError(f"compiled ingest SQL has no CREATE TABLE for {table_name!r}")
    open_idx = m.end() - 1
    depth = 0
    for i in range(open_idx, len(sql)):
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return sql[open_idx + 1 : i].splitlines()
    raise ValueError(  # pragma: no cover - compiled DDL is always balanced
        f"unbalanced parentheses in CREATE TABLE {table_name}"
    )


def _parse_columns(body_lines: list[str]) -> list[tuple[str, str]]:
    """Parse ``(name, type_token)`` pairs from CREATE-TABLE body lines."""
    cols: list[tuple[str, str]] = []
    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = _COL_LINE.match(line)
        if m is None:  # pragma: no cover - every body line is a column def
            continue
        cols.append((m.group(1), m.group(2).strip().rstrip(",").strip()))
    return cols


def parse_ingest_sql(ingest_sql: str, table: str) -> CompiledSchema:
    """Derive the runtime :class:`CompiledSchema` from the compiled ingest SQL.

    Reads the column order from the RAW landing CREATE TABLE (business columns only,
    dropping ``_source_file`` / ``_load_ts``) and the decimal scales from the TYPED
    target CREATE TABLE. The two share the same business-column order, so the typed
    table is only consulted for scales.
    """
    raw_table = f"raw_{table}"
    ingested_table = f"ingested_{table}"

    raw_cols = _parse_columns(_create_table_body(ingest_sql, raw_table))
    columns = [name for name, _ in raw_cols if name not in _META_COLUMNS]

    typed_cols = _parse_columns(_create_table_body(ingest_sql, ingested_table))
    scales: dict[str, int | None] = {}
    for name, type_token in typed_cols:
        dm = _DECIMAL.search(type_token)
        if dm is not None:
            scales[name] = int(dm.group(1))

    return CompiledSchema(
        raw_table=raw_table,
        ingested_table=ingested_table,
        columns=columns,
        decimal_scales=scales,
    )


def load_compiled_schema(ingest_sql_path: Path, table: str) -> CompiledSchema:
    """Load + parse the compiled ingest SQL artifact at *ingest_sql_path*."""
    return parse_ingest_sql(ingest_sql_path.read_text(), table)
