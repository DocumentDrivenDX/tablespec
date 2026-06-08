"""Shared dialect validation and normalization helpers.

This module centralizes the accepted dialect spellings used by the cast and dbt
renderers so alias handling and error text stay consistent across call sites.
"""

from __future__ import annotations

CAST_DIALECTS: tuple[str, ...] = ("spark", "databricks", "duckdb")
PROFILE_TARGETS: tuple[str, ...] = ("duckdb", "spark", "databricks")


def _format_accepted_values(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def _unsupported_value_message(label: str, value: str, values: tuple[str, ...]) -> str:
    return (
        f"Unsupported {label}: {value!r} "
        f"(expected one of {_format_accepted_values(values)})"
    )


def normalize_cast_dialect(dialect: str, *, label: str = "dialect") -> str:
    """Validate a cast dialect and return the render-path dialect.

    ``databricks`` is an explicit public spelling, but it renders through the
    Spark-family cast path.
    """
    if dialect not in CAST_DIALECTS:
        raise ValueError(_unsupported_value_message(label, dialect, CAST_DIALECTS))
    return "duckdb" if dialect == "duckdb" else "spark"


def validate_profile_target(target: str) -> str:
    """Validate a dbt profile target and return it unchanged."""
    if target not in PROFILE_TARGETS:
        raise ValueError(
            _unsupported_value_message("profile target", target, PROFILE_TARGETS)
        )
    return target
