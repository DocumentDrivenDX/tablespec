"""Spark session management and capability probing.

This module centralizes obtaining a Spark session and detecting per-session
capabilities that vary across Spark builds (e.g. classic Spark 4.0 vs some
Spark Connect builds).

All PySpark imports are lazy so that ``import tablespec.session`` succeeds even
when PySpark is not installed. Callers that actually invoke a session or probe
require PySpark at call time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)

# Cache of per-session capabilities, keyed by id(spark).
_session_capabilities: dict[int, dict[str, bool]] = {}


def _probe_try_to_timestamp_with_format(spark: object) -> bool:
    """Probe whether ``F.try_to_timestamp(col, F.lit(fmt))`` works on this session.

    This expression works on classic Spark 4.0 but may not on some Spark Connect
    builds. We evaluate a tiny 1-row DataFrame expression and return True on
    success, False on any failure.

    PySpark is imported lazily so the module imports cleanly without PySpark.
    """
    try:
        from pyspark.sql import functions as F  # noqa: N812

        df = spark.createDataFrame([("2020-01-01",)], ["d"])  # type: ignore[attr-defined]
        expr = F.try_to_timestamp(df["d"], F.lit("yyyy-MM-dd"))
        df.select(expr).collect()
    except Exception:
        return False
    else:
        return True


def get_capabilities(spark: object) -> dict[str, bool]:
    """Return capability flags for the given Spark session, with caching.

    The result is cached keyed by ``id(spark)``. On a cache miss the relevant
    probes are run; on a cache hit the cached result is returned without
    re-probing.
    """
    key = id(spark)
    cached = _session_capabilities.get(key)
    if cached is not None:
        return cached

    capabilities = {
        "try_to_timestamp_with_format": _probe_try_to_timestamp_with_format(spark),
    }
    _session_capabilities[key] = capabilities
    return capabilities


def get_session(app_name: str = "tablespec", backend: str = "spark") -> SparkSession:
    """Obtain a Spark session.

    Args:
    ----
        app_name: Name of the Spark application.
        backend: Session backend. Currently only ``"spark"`` is supported.

    Returns:
    -------
        An active or newly created SparkSession.

    """
    if backend != "spark":
        msg = f"Unknown backend: {backend}"
        raise ValueError(msg)

    from pyspark.sql import SparkSession

    from tablespec.spark_factory import SparkSessionFactory

    try:
        existing = SparkSession.getActiveSession()
    except Exception:
        existing = None
    if existing is not None:
        return existing

    return SparkSessionFactory.create_session(app_name)


__all__ = [
    "get_capabilities",
    "get_session",
]
