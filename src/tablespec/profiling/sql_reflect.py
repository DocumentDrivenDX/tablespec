"""Spark-free UMF reflection from SQL catalog metadata (INFORMATION_SCHEMA).

Consistent with the rest of tablespec, this module never opens a database
connection: the caller runs the ``INFORMATION_SCHEMA.COLUMNS`` query against
whatever it owns (a SQL warehouse, a JDBC link, a dbt ``catalog.json``) and
hands the resulting rows here.

This is the path Databricks Apps need. An App has a SQL warehouse and the
workspace SDK but **no SparkSession**, so neither
:class:`~tablespec.profiling.spark_mapper.SparkToUmfMapper` (needs a
DataFrame) nor :class:`~tablespec.profiling.jdbc_mapper.JdbcToUmfMapper`
(needs ``spark.read.format("jdbc")``) can run there.

``SQL_TO_UMF_TYPE`` lives here rather than in ``spark_mapper`` so it is
importable without pyspark; ``spark_mapper`` re-imports it, keeping exactly one
type-mapping seam.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import logging
from typing import Any

from tablespec.models.umf import UMF

logger = logging.getLogger(__name__)

__all__ = [
    "SQL_TO_UMF_TYPE",
    "ColumnMeta",
    "column_meta_from_row",
    "normalize_sql_type",
    "umf_from_information_schema",
]

# Declared SQL type -> UMF data_type. Useful when importing from dbt
# catalog.json, INFORMATION_SCHEMA, or DESCRIBE output.
SQL_TO_UMF_TYPE: dict[str, str] = {
    "STRING": "VARCHAR",
    "VARCHAR": "VARCHAR",
    "CHAR": "CHAR",
    "TEXT": "TEXT",
    "INT": "INTEGER",
    "INTEGER": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    "TINYINT": "INTEGER",
    "LONG": "INTEGER",
    "FLOAT": "FLOAT",
    "DOUBLE": "FLOAT",
    "REAL": "FLOAT",
    "DECIMAL": "DECIMAL",
    "NUMERIC": "DECIMAL",
    "NUMBER": "DECIMAL",
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "DATETIME",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMP_NTZ": "TIMESTAMP",
    "TIMESTAMP_LTZ": "TIMESTAMP",
}

# Types that carry a character length worth recording on the UMF column.
_LENGTH_TYPES = frozenset({"VARCHAR", "CHAR"})

# Fallback when a declared type has no UMF equivalent (ARRAY/MAP/STRUCT/VARIANT).
_UNMAPPED_FALLBACK = "VARCHAR"


def normalize_sql_type(declared: str) -> str | None:
    """Map a declared SQL type to a UMF type, or ``None`` if unmapped.

    National variants (``nchar``/``nvarchar``/``ntext``) resolve through their
    base names. Parameterized spellings (``decimal(10,2)``, ``varchar(50)``)
    are reduced to their base name first.
    """
    base = declared.strip().upper()
    base = base.split("(", 1)[0].strip()
    if base not in SQL_TO_UMF_TYPE and base.startswith("N"):
        base = base[1:]
    return SQL_TO_UMF_TYPE.get(base)


@dataclass(frozen=True)
class ColumnMeta:
    """One column's metadata as reported by ``INFORMATION_SCHEMA.COLUMNS``."""

    name: str
    data_type: str
    is_nullable: bool = True
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    comment: str | None = None
    ordinal_position: int | None = None


def _as_bool(value: Any) -> bool:
    """INFORMATION_SCHEMA reports nullability as 'YES'/'NO' (or a bool)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"YES", "TRUE", "1"}


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def column_meta_from_row(row: Mapping[str, Any]) -> ColumnMeta:
    """Build a :class:`ColumnMeta` from one INFORMATION_SCHEMA row.

    Keys are matched case-insensitively so both ``column_name`` (Databricks)
    and ``COLUMN_NAME`` (SQL Server) style rows work unchanged.
    """
    lower = {str(k).lower(): v for k, v in row.items()}
    return ColumnMeta(
        name=str(lower["column_name"]),
        data_type=str(lower["data_type"]),
        is_nullable=_as_bool(lower.get("is_nullable", True)),
        character_maximum_length=_as_int(lower.get("character_maximum_length")),
        numeric_precision=_as_int(lower.get("numeric_precision")),
        numeric_scale=_as_int(lower.get("numeric_scale")),
        comment=(lower.get("comment") or None),
        ordinal_position=_as_int(lower.get("ordinal_position")),
    )


def umf_from_information_schema(
    table_name: str,
    columns: Iterable[ColumnMeta | Mapping[str, Any]],
    *,
    table_type: str = "inferred",
    description: str | None = None,
) -> UMF:
    """Build a :class:`UMF` from INFORMATION_SCHEMA column metadata.

    Columns are emitted in ``ordinal_position`` order when every row carries
    one; otherwise the caller's iteration order is preserved (so a query with
    ``ORDER BY ordinal_position`` also works).

    A declared type with no UMF equivalent (``ARRAY``, ``MAP``, ``STRUCT``,
    ``VARIANT``) is mapped to ``VARCHAR`` and logged -- never silently dropped,
    since dropping a column would misrepresent the table's shape.
    """
    metas: Sequence[ColumnMeta] = [
        c if isinstance(c, ColumnMeta) else column_meta_from_row(c) for c in columns
    ]
    if metas and all(m.ordinal_position is not None for m in metas):
        metas = sorted(metas, key=lambda m: m.ordinal_position or 0)

    umf_columns: list[dict[str, Any]] = []
    for meta in metas:
        umf_type = normalize_sql_type(meta.data_type)
        if umf_type is None:
            logger.warning(
                "Column %r has unmapped SQL type %r; recording it as %s.",
                meta.name,
                meta.data_type,
                _UNMAPPED_FALLBACK,
            )
            umf_type = _UNMAPPED_FALLBACK

        column: dict[str, Any] = {
            "name": meta.name,
            "data_type": umf_type,
            # `Nullable` carries per-context flags (LOB, region, env). A
            # schema-only reflection has no context, so it records the single
            # `default` key -- the same shape bootstrap_from_tables emits.
            "nullable": {"default": meta.is_nullable},
            "description": meta.comment
            or f"{meta.name} (reflected from information_schema)",
        }
        if umf_type in _LENGTH_TYPES and meta.character_maximum_length:
            column["length"] = meta.character_maximum_length
        if umf_type == "DECIMAL":
            if meta.numeric_precision is not None:
                column["precision"] = meta.numeric_precision
            if meta.numeric_scale is not None:
                column["scale"] = meta.numeric_scale

        umf_columns.append(column)

    payload: dict[str, Any] = {
        "version": "1.0",
        "table_name": table_name,
        "table_type": table_type,
        "columns": umf_columns,
    }
    if description:
        payload["description"] = description

    logger.info(
        "Reflected %s from information_schema: %d columns",
        table_name,
        len(umf_columns),
    )
    return UMF.model_validate(payload)
