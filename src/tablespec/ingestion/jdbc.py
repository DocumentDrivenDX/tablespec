"""JDBC source reading (FEAT-031 JDBC-01..05 / ADR-015 decision points 4-6).

tablespec never opens a database connection itself: :class:`JdbcReader` only
derives ``spark.read.format("jdbc")`` options from a
:class:`~tablespec.models.umf.JdbcSource` spec and hands them to the caller's
Spark session, which owns all connectivity (JDBC-02). Credentials exist only
as named secret references (``password_secret_ref``); they are resolved at
read time, never persisted, and never logged (JDBC-01/JDBC-04).

This module never imports PySpark at module import time -- readers receive an
active session, keeping ``tablespec[spark]`` optional (ADR-003).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from tablespec.models.umf import JdbcSource

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from tablespec.models.umf import SourceSpec

__all__ = [
    "JdbcReader",
    "SecretResolutionError",
    "jdbc_connection_options",
    "jdbc_options",
    "quote_identifier",
    "resolve_secret_ref",
    "sanitize_identifier",
]


class SecretResolutionError(ValueError):
    """A ``password_secret_ref`` could not be resolved (JDBC-04).

    Raised BEFORE any read is attempted -- never a silent skip or empty read.
    The message names the missing reference; it never contains credential
    material.
    """


# -- JDBC-05: deterministic identifier sanitization ---------------------------
#
# Canonical column/table names are derived from source identifiers with the
# rules proven in the entropy-exchange ``mssql_import`` bundle: lowercase,
# non-alphanumerics -> underscore, repeated underscores collapsed, leading and
# trailing underscores stripped. CamelCase word boundaries become underscores
# BEFORE lowercasing so SQL Server-style identifiers land on the canonical
# names US-039 fixes (``CustomerID`` -> ``customer_id``, ``Order Details`` ->
# ``order_details``); without that split, lowercasing alone would fuse the
# words (``customerid``) and the discovered specs could never carry the FK
# graph the story asserts.
_CAMEL_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")  # "ABCName" -> "ABC_Name"
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")  # "CustomerID" -> "Customer_ID"
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def sanitize_identifier(name: str) -> str:
    """Sanitize a source identifier to a canonical snake_case name (JDBC-05).

    Deterministic: ``"Order Details"`` -> ``"order_details"``, ``"CustomerID"``
    -> ``"customer_id"``. Bracket/backtick quoting is NOT this function's job;
    quoting of the ORIGINAL identifier happens at the read boundary
    (:func:`quote_identifier`), and the original is preserved in the spec.
    """
    sanitized = _CAMEL_ACRONYM.sub("_", name)
    sanitized = _CAMEL_BOUNDARY.sub("_", sanitized)
    sanitized = _NON_ALNUM.sub("_", sanitized).lower().strip("_")
    sanitized = re.sub(r"_+", "_", sanitized)
    if not sanitized:
        msg = f"identifier {name!r} sanitizes to an empty name"
        raise ValueError(msg)
    return sanitized


def quote_identifier(name: str, url: str = "") -> str:
    """Quote an ORIGINAL source identifier for use inside SQL at the read boundary.

    SQL Server URLs (``jdbc:sqlserver:``) take bracket quoting; everything else
    gets ANSI double quotes. Embedded closing delimiters are doubled.
    """
    if url.startswith("jdbc:sqlserver:"):
        return "[" + name.replace("]", "]]") + "]"
    return '"' + name.replace('"', '""') + '"'


# -- Option building (pure; no Spark, no credentials) --------------------------


def jdbc_connection_options(spec: JdbcSource) -> dict[str, str]:
    """Connection-level Spark JDBC options from *spec* -- never credentials.

    Excludes ``dbtable``/``query`` so discovery can issue its own metadata
    queries over the same connection parameters.
    """
    options: dict[str, str] = {"url": spec.url}
    if spec.driver is not None:
        options["driver"] = spec.driver
    if spec.user is not None:
        options["user"] = spec.user
    if spec.fetch_size is not None:
        options["fetchsize"] = str(spec.fetch_size)
    return options


def jdbc_options(spec: JdbcSource) -> dict[str, str]:
    """All Spark ``DataFrameReader`` JDBC options *spec* declares.

    Pure and deterministic: credentials are NOT included here -- the password
    is resolved separately at read time (:func:`resolve_secret_ref`) so no
    option dict ever carries credential material into logs or artifacts.
    """
    options = jdbc_connection_options(spec)
    if spec.dbtable is not None:
        options["dbtable"] = spec.dbtable
    if spec.query is not None:
        options["query"] = spec.query
    if spec.partition_column is not None:
        options["partitionColumn"] = spec.partition_column
    if spec.lower_bound is not None:
        options["lowerBound"] = str(spec.lower_bound)
    if spec.upper_bound is not None:
        options["upperBound"] = str(spec.upper_bound)
    if spec.num_partitions is not None:
        options["numPartitions"] = str(spec.num_partitions)
    return options


# -- JDBC-04: read-time secret resolution (fail closed, never logged) ----------


def _databricks_dbutils() -> Any | None:
    """Return ``dbutils`` when running inside a Databricks runtime, else None."""
    if "DATABRICKS_RUNTIME_VERSION" not in os.environ:
        return None
    try:
        from databricks.sdk.runtime import dbutils  # noqa: PLC0415
    except ImportError:
        return None
    return dbutils


def resolve_secret_ref(ref: str) -> str:
    """Resolve a ``password_secret_ref`` to the credential it names (JDBC-04).

    A ref containing ``/`` is a Databricks secret ``scope/key`` (resolved via
    ``dbutils`` when the runtime provides one; outside Databricks it fails
    closed). Any other ref is an environment-variable name. An unresolvable
    ref raises :class:`SecretResolutionError` naming the reference -- BEFORE
    any read is attempted. The resolved value is returned to the caller only;
    it is never logged or echoed.
    """
    if "/" in ref:
        scope, _, key = ref.partition("/")
        dbutils = _databricks_dbutils()
        if dbutils is None:
            msg = (
                f"Cannot resolve password_secret_ref {ref!r}: it names a "
                f"Databricks secret (scope {scope!r}, key {key!r}) but no "
                "Databricks runtime/dbutils is available here. Run on "
                "Databricks, or use an environment-variable reference "
                "(a ref without '/')."
            )
            raise SecretResolutionError(msg)
        try:
            return dbutils.secrets.get(scope=scope, key=key)
        except Exception as exc:
            msg = (
                f"Cannot resolve password_secret_ref {ref!r}: dbutils.secrets"
                f".get(scope={scope!r}, key={key!r}) failed: {exc}"
            )
            raise SecretResolutionError(msg) from exc
    value = os.environ.get(ref)
    if value is None:
        msg = (
            f"Cannot resolve password_secret_ref {ref!r}: no environment "
            f"variable named {ref!r} is set. Export it, or reference a "
            "Databricks secret as 'scope/key'."
        )
        raise SecretResolutionError(msg)
    return value


class JdbcReader:
    """JDBC source reader: ``spark.read.format("jdbc")`` with UMF-derived options.

    tablespec compiles the read spec; the caller's Spark session performs the
    read (JDBC-02). ``password_secret_ref`` is resolved at read time and
    handed to Spark as the ``password`` option only -- it never enters the
    spec, the UMF, or any log line.
    """

    def read(self, spec: SourceSpec, spark: SparkSession) -> DataFrame:
        """Read the table/query *spec* describes using the active *spark* session."""
        if not isinstance(spec, JdbcSource):
            msg = f"JdbcReader requires a jdbc source, got kind={spec.kind!r}"
            raise TypeError(msg)
        options = jdbc_options(spec)
        if spec.password_secret_ref is not None:
            # JDBC-04: resolve (and fail closed) BEFORE any read is attempted.
            options["password"] = resolve_secret_ref(spec.password_secret_ref)
        return spark.read.format("jdbc").options(**options).load()
