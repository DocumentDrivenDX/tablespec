"""Render dbt model *contracts* from engine-agnostic :class:`ColumnContract` facts.

A dbt model contract is two coordinated pieces of project text:

  * the model ``config`` opts into enforcement -- ``contract={"enforced": True}``
    -- so the adapter checks the materialized relation against the declared shape;
  * each column in ``schema.yml`` declares a ``data_type`` (an adapter SQL type)
    and, when the column is non-nullable, a ``not_null`` ``constraints:`` entry.

dbt-duckdb (and adapters generally) enforce the contract at BUILD/materialization
time, not at ``parse``: when the model's SELECT produces a column whose type
differs from the declared ``data_type``, ``dbt build`` FAILS with a contract
mismatch; a ``not_null`` constraint violated by the data also fails the build.

The derivation (which columns, their UMF type + precision/scale/length, and
not-null) lives in :func:`tablespec.core.schema_facts.column_contracts`; this
module owns ONLY the dbt YAML/SQL *text*, mapping the logical UMF type to the
adapter SQL type so the declared contract matches the SELECT output of the shared
cast (``build_ingest_select``):

  * ``VARCHAR``/``TEXT``/``CHAR`` -> ``VARCHAR(n)`` when a length is given else
    ``VARCHAR`` (the raw landing column is already a string -- passthrough);
  * ``INTEGER`` -> ``INTEGER`` (the duckdb cast targets ``INT`` == ``INTEGER``);
  * ``DECIMAL`` -> ``DECIMAL(p,s)`` (defaults ``p=10,s=2`` mirror the caster);
  * ``FLOAT``/``DOUBLE`` -> ``DOUBLE`` (the runtime maps FLOAT to double);
  * ``DATE`` -> ``DATE``; ``DATETIME``/``TIMESTAMP`` -> ``TIMESTAMP``;
  * ``BOOLEAN`` -> ``BOOLEAN``.

Pure text emission -- importing this module never imports any ``dbt`` package
(the ``[dbt]`` extra is only needed to *run* the generated project).
"""

from __future__ import annotations

from tablespec.core.schema_facts import ColumnContract

# duckdb adapter SQL types keyed by the logical UMF type. These match the column
# types the shared duckdb cast SELECT (``cast_column_sql(dialect="duckdb")``)
# actually produces, so an enforced contract over that SELECT validates cleanly.
_DUCKDB_TYPE: dict[str, str] = {
    "VARCHAR": "VARCHAR",
    "TEXT": "VARCHAR",
    "CHAR": "VARCHAR",
    "STRING": "VARCHAR",
    "INTEGER": "INTEGER",
    "FLOAT": "DOUBLE",
    "DOUBLE": "DOUBLE",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
}

# Supported emit dialects (duckdb is the only build target wired today; spark is
# kept symmetric for callers that render a Databricks-flavoured contract).
_SPARK_TYPE: dict[str, str] = {
    "VARCHAR": "STRING",
    "TEXT": "STRING",
    "CHAR": "STRING",
    "STRING": "STRING",
    "INTEGER": "INT",
    "FLOAT": "DOUBLE",
    "DOUBLE": "DOUBLE",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
}

# Databricks SQL types == Spark SQL types, so the Databricks dialect reuses the
# Spark contract type map (kept as a distinct, explicitly-selectable key so a
# Databricks target renders its contract under its own name without drifting).
_TYPE_BY_DIALECT: dict[str, dict[str, str]] = {
    "duckdb": _DUCKDB_TYPE,
    "spark": _SPARK_TYPE,
    "databricks": _SPARK_TYPE,
}


def contract_sql_type(contract: ColumnContract, *, dialect: str = "duckdb") -> str:
    """Map a :class:`ColumnContract` to its adapter SQL type string for *dialect*.

    Applies the precision/scale/length modifiers exactly as ``generate_sql_ddl``
    /the cast target does: ``DECIMAL(p,s)`` (defaults 10,2), ``VARCHAR(n)`` when a
    length is declared (duckdb only -- spark renders bare ``STRING``), else the
    base type.
    """
    if dialect not in _TYPE_BY_DIALECT:
        msg = (
            f"Unsupported contract dialect: {dialect!r} "
            "(expected 'duckdb'/'spark'/'databricks')"
        )
        raise ValueError(msg)
    table = _TYPE_BY_DIALECT[dialect]
    dt = contract.data_type.upper()

    if dt == "DECIMAL":
        precision = contract.precision or 10
        scale = contract.scale if contract.scale is not None else 2
        return f"DECIMAL({precision},{scale})"

    base = table.get(dt, table["VARCHAR"])
    # duckdb VARCHAR carries an optional length; spark uses bare STRING (its
    # VARCHAR(n) requires a size and the ingest target uses STRING).
    if base == "VARCHAR" and contract.length:
        return f"VARCHAR({contract.length})"
    return base


def render_contract_config_arg() -> str:
    """Render the ``contract={...}`` keyword argument line for a ``config(...)`` block.

    Returned WITHOUT a trailing comma and at 8-space indentation so a caller can
    splice it into the existing ``    config(\\n        ...\\n    )`` body the same
    way the ``materialized=`` / ``unique_key=`` lines are emitted.
    """
    return "        contract={'enforced': True},"


def render_column_contract(
    contract: ColumnContract, *, dialect: str = "duckdb"
) -> list[str]:
    """Render one column's contract lines for a ``schema.yml`` ``columns:`` block.

    Emits the ``- name:`` entry with a ``data_type:`` and, for a non-nullable
    column, a ``constraints:`` list with a single ``not_null`` entry. The column
    sits at 6-space indent (``      - name: x``) to match the existing layout.

    NOTE: a column may ALSO carry generic ``data_tests:`` (not_null/unique/
    relationships/accepted_values). This function renders only the contract
    portion (``data_type`` + ``constraints``); the caller appends any
    ``data_tests:`` block after these lines so one column entry carries both.
    """
    sql_type = contract_sql_type(contract, dialect=dialect)
    lines = [
        f"      - name: {contract.name}",
        f"        data_type: {sql_type}",
    ]
    if contract.not_null:
        lines.append("        constraints:")
        lines.append("          - type: not_null")
    return lines


__all__ = [
    "contract_sql_type",
    "render_column_contract",
    "render_contract_config_arg",
]
