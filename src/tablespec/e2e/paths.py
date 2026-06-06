"""The two compile ENTRY POINTS that produce the UMF set fed to the orchestrator.

Both return ``list[UMF]`` so :func:`tablespec.e2e.compile.compile_umfs` is
path-agnostic.

Path A -- existing tables (``bootstrap_from_tables``)
=====================================================
``spark.table(name)`` -> :meth:`SparkToUmfMapper.map_dataframe_to_umf` (SCHEMA-only
inference). RECOMMENDED to additionally ENRICH each table via
:class:`NativeSparkProfiler` + :class:`ProfileToGxMapper` so the compiled suite
carries data-derived expectations.

    Why profile-enriched (recommended), not schema-only:
      * Schema-only inference yields a UMF with column names + types only -- the
        compiled baseline suite degrades to structural + type checks. That is a
        weak runtime contract for tables that ALREADY exist and whose data we can
        observe for free.
      * The profiling seam already exists and emits GX expectation dicts in the
        SAME shape ``execute_staged`` consumes (completeness, uniqueness, ranges,
        value sets, patterns, lengths) -- enrichment is additive and reuses merged
        code, no new harness.
      * Cost is bounded: profiling is opt-in per call and the backbone runs on a
        local Spark/Connect session, so the extra scan is acceptable for the demo.
    Therefore Path A DEFAULTS to ``profile=True`` and the enriched expectations are
    handed to the orchestrator as precompiled ``suites``; ``profile=False`` remains
    available for the pure schema-only contract.

Path B -- specs (``bootstrap_from_specs``)
==========================================
:func:`tablespec.models.umf.load_umf_from_yaml` per spec file. No Spark required to
LOAD; the backbone still needs a session to EXECUTE the compiled artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tablespec.models.umf import UMF


def umfs_from_tables(
    spark: Any,
    table_names: list[str],
    *,
    profile: bool = True,
) -> tuple[list[UMF], dict[str, list[dict]]]:
    """Path A: infer a UMF set from existing Spark tables (optionally enriched).

    For each name: ``spark.table(name)`` -> ``SparkToUmfMapper.map_dataframe_to_umf``
    (schema-only) -> :class:`UMF`. When *profile* is True, additionally run
    ``NativeSparkProfiler.profile`` + ``ProfileToGxMapper.build_expectations`` and
    return those expectation dicts so the orchestrator persists them as the
    compiled suite for that table.

    Args:
        spark: an active Spark (classic or Connect) session.
        table_names: tables to reflect + (optionally) profile.
        profile: enrich with profile-derived expectations (recommended default).

    Returns:
        ``(umfs, suites)`` where ``suites`` maps table name -> precompiled
        expectation list (empty dict when ``profile`` is False -- the orchestrator
        then generates baseline suites from the UMF).
    """
    from tablespec.models.umf import UMF
    from tablespec.profiling.spark_mapper import SparkToUmfMapper

    mapper = SparkToUmfMapper()
    umfs: list[UMF] = []
    suites: dict[str, list[dict]] = {}

    for full_name in table_names:
        # Reflect the (possibly schema-qualified) table to a bare-name UMF: the
        # compiled raw/ingested tables are unqualified (raw_<t>/ingested_<t>).
        df = spark.table(full_name)
        table = full_name.split(".")[-1]
        umf_data = _to_strict_umf_data(mapper.map_dataframe_to_umf(df, table))
        umfs.append(UMF(**umf_data))

        if profile:
            from tablespec.profiling.gx_expectation_builder import ProfileToGxMapper
            from tablespec.profiling.native_profiler import NativeSparkProfiler

            profile_result = NativeSparkProfiler(spark).profile(df)
            suites[table] = ProfileToGxMapper().build_expectations(profile_result)

    return umfs, suites


def umfs_from_specs(spec_paths: list[str | Path]) -> list[UMF]:
    """Path B: load a UMF set from spec YAML files via ``load_umf_from_yaml``.

    Args:
        spec_paths: UMF ``.yaml`` spec files (one table each).

    Returns:
        The loaded :class:`UMF` models, in input order.
    """
    from tablespec.models.umf import load_umf_from_yaml

    return [load_umf_from_yaml(p) for p in spec_paths]


def _to_strict_umf_data(base: dict[str, Any]) -> dict[str, Any]:
    """Normalize ``SparkToUmfMapper`` output into the strict UMF model shape.

    ``map_dataframe_to_umf`` emits a BASE schema dict (``nullable: bool``, no
    ``version``) tuned for downstream tooling; the strict :class:`UMF` model the
    compile orchestrator consumes requires a ``version`` and a ``Nullable``-shaped
    ``nullable``. This adapts the reflected dict in place so Path A produces the
    same ``UMF`` type as Path B.
    """
    data = dict(base)
    data.setdefault("version", "1.0")
    cols = []
    for col in data.get("columns", []):
        col = dict(col)
        nullable = col.get("nullable")
        if isinstance(nullable, bool):
            col["nullable"] = {"default": nullable}
        cols.append(col)
    data["columns"] = cols
    return data
