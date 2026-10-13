# @covers US-039-AC1
# @covers US-039-AC2
# @covers US-039-AC3
# @covers US-039-AC4
# @covers US-039-AC5
# @covers US-039-AC6
"""US-039 Northwind end-to-end acceptance run (FEAT-031, bead tablespec-8980c812).

Composes the shipped features over ONE discovered-UMF session (the shared
fixtures in ``tests/integration/conftest.py``):

* AC1..AC3 (discovery / sanitization / spec validity) are proven in depth by
  ``test_jdbc_discovery.py``; here only the flow-level versions are asserted
  (13 UMFs, the orders->customers FK, every spec validates).
* AC4 -- schema workbook: every discovered UMF exports to xlsx
  (FEAT-009 ``UMFToExcelConverter``, one workbook per table) and re-imports
  with tables/columns/types/keys preserved (the converter's own round-trip
  semantics).
* AC5 -- sample data: FK-aware generation (FEAT-011) from the discovered
  specs with a pinned deterministic config; every table gets data and every
  generated ``orders.customer_id`` exists among generated
  ``customers.customer_id`` values.
* AC6 -- validation report: ``customers``/``orders``/``order_details`` are
  landed TYPED via ``JdbcReader``, baseline suites are composed from the
  discovered UMFs (typed raw receives NO string-shape checks,
  FEAT-031 SUITE-01/02), staged execution (FEAT-007/FEAT-017) produces a
  per-table ``ValidationReport`` with real per-expectation results, and the
  landed ``orders.order_date`` values are non-null (zero silent NULL-out,
  PARQ-02/JDBC-03).

Lanes:

* Local Docker lane (default): SQL Server 2022 container; SKIPS, never
  fails, when Docker is unavailable.
* Databricks lane (opt-in ``databricks_e2e`` tier): the same flow against a
  workspace-reachable SQL Server (consumer-owned, US-039), gated on the
  shipped gate (``tablespec.e2e.gating.databricks_e2e_availability``) PLUS
  ``TABLESPEC_NORTHWIND_JDBC_URL``.
"""

from __future__ import annotations

import csv
import json
import os
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("pyspark", reason="PySpark required for the JDBC lanes")

from tablespec.excel_converter import (  # noqa: E402
    ExcelToUMFConverter,
    UMFToExcelConverter,
)
from tablespec.gx_baseline import (  # noqa: E402
    STRING_SHAPE_EXPECTATION_TYPES,
    BaselineExpectationGenerator,
)
from tablespec.ingestion import get_reader  # noqa: E402
from tablespec.ingestion.raw_ingester import (  # noqa: E402
    build_column_lookup,
    map_headers,
)
from tablespec.sample_data import GenerationConfig, SampleDataGenerator  # noqa: E402
from tablespec.umf_validator import UMFValidator  # noqa: E402
from tablespec.validation.gx_executor import GXSuiteExecutor  # noqa: E402
from tablespec.validation.staged_report import (  # noqa: E402
    build_validation_report_from_staged_execution,
)
from tablespec.validation.report import ValidationReport  # noqa: E402

from tests.integration.conftest import EXPECTED_TABLES, MSSQL_DRIVER  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

    from tablespec.models.umf import UMF

pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.slow,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

#: Opt-in env for the Databricks lane: the JDBC URL of a workspace-reachable
#: SQL Server with Northwind restored (consumer-owned precondition, US-039).
NORTHWIND_URL_ENV = "TABLESPEC_NORTHWIND_JDBC_URL"

#: The AC6 tables landed through the reader seam.
AC6_TABLES = ("customers", "orders", "order_details")

#: Expected fixture row counts for the AC6 tables (tests/fixtures/northwind).
FIXTURE_ROW_COUNTS = {"customers": 3, "orders": 3, "order_details": 4}


# ---------------------------------------------------------------------------
# Flow steps (shared verbatim by the Docker lane and the Databricks lane)
# ---------------------------------------------------------------------------


def _assert_discovery_flow(discovered: dict[str, UMF]) -> None:
    """AC1/AC2/AC3, flow-level: 13 UMFs, FK graph seed, every spec validates."""
    assert set(discovered) == EXPECTED_TABLES
    assert len(discovered) == 13

    # AC1 seed: the FK the story names, present in the discovered graph.
    orders_fks = {
        (fk.column, fk.references_table, fk.references_column)
        for fk in (discovered["orders"].relationships.foreign_keys or [])
    }
    assert ("customer_id", "customers", "customer_id") in orders_fks

    # AC2 seed: sanitized identifier with the original preserved.
    assert discovered["order_details"].canonical_name == "Order Details"

    # AC3: every discovered spec passes validation unmodified (depth --
    # including the CLI surface -- lives in test_jdbc_discovery.py).
    validator = UMFValidator()
    for name, umf in discovered.items():
        assert validator.validate_data(
            umf.model_dump(mode="json", exclude_none=True), source_name=name
        ), f"discovered spec for {name} failed validation"


def _assert_excel_roundtrip(discovered: dict[str, UMF], out_dir: Path) -> None:
    """AC4: export every discovered UMF to xlsx, re-import, compare.

    The Excel converter's contract (FEAT-009) is ONE WORKBOOK PER TABLE; the
    round-trip preserves table identity, column order, types, widths, the
    primary key, the discovered ``source:`` block, and discovered
    ``relationships.foreign_keys``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    exporter = UMFToExcelConverter()
    importer = ExcelToUMFConverter()

    for name, umf in discovered.items():
        workbook_path = out_dir / f"{name}.xlsx"
        exporter.convert(umf).save(workbook_path)
        assert workbook_path.exists()

        reimported, _review_notes = importer.convert(workbook_path)

        assert reimported.table_name == umf.table_name
        assert reimported.canonical_name == umf.canonical_name
        assert reimported.primary_key == umf.primary_key

        # One sheet row per column, in order, with types/widths preserved.
        assert [c.name for c in reimported.columns] == [c.name for c in umf.columns]
        for original, roundtripped in zip(umf.columns, reimported.columns, strict=True):
            ctx = f"{name}.{original.name}"
            assert roundtripped.canonical_name == original.canonical_name, ctx
            assert roundtripped.data_type == original.data_type, ctx
            assert roundtripped.length == original.length, ctx
            assert roundtripped.precision == original.precision, ctx
            assert roundtripped.scale == original.scale, ctx
            if original.nullable is not None:
                assert roundtripped.nullable is not None, ctx
                assert roundtripped.nullable.model_dump(exclude_none=True) == (
                    original.nullable.model_dump(exclude_none=True)
                ), ctx

        if umf.source is not None:
            assert reimported.source is not None, name
            assert reimported.source.model_dump(
                exclude_none=True
            ) == umf.source.model_dump(exclude_none=True), name

        if umf.relationships and umf.relationships.foreign_keys:
            assert reimported.relationships is not None, name
            assert reimported.relationships.foreign_keys is not None, name
            assert [
                fk.model_dump(exclude_none=True)
                for fk in reimported.relationships.foreign_keys
            ] == [
                fk.model_dump(exclude_none=True)
                for fk in umf.relationships.foreign_keys
            ], name


def _pinned_generation_config() -> GenerationConfig:
    """Deterministic AC5 config: pinned seed + uniform FK pools.

    ``key_distribution_80_20=False`` with a small shared pool makes the FK
    subset property (orders ⊆ customers) statistically certain on top of the
    pinned seed: with 6 pool values drawn uniformly for 120 ``customers``
    rows, the chance any pool value is absent from ``customers`` is ~1e-9.
    """
    return GenerationConfig(
        num_members=120,
        key_pool_size=6,
        key_distribution_80_20=False,
        random_seed=42,
    )


def _read_generated_table(path: Path) -> list[dict[str, str]]:
    """Parse a generated pipe-delimited sample file (canonical-name headers)."""
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def _assert_sample_data(
    discovered: dict[str, UMF], specs_dir: Path, data_dir: Path
) -> None:
    """AC5: FK-aware sample data for every table from the discovered specs."""
    tables_dir = specs_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    for name, umf in discovered.items():
        (tables_dir / f"{name}.json").write_text(
            json.dumps(umf.model_dump(mode="json", exclude_none=True), indent=2)
        )

    generator = SampleDataGenerator(
        input_dir=specs_dir,
        output_dir=data_dir,
        config=_pinned_generation_config(),
    )
    assert generator.run_generation() is True

    # Every table got data.
    rows_by_table: dict[str, list[dict[str, str]]] = {}
    for name in discovered:
        data_file = data_dir / f"{name}.txt"
        assert data_file.exists(), f"no sample data generated for {name}"
        rows = _read_generated_table(data_file)
        assert rows, f"sample data file for {name} is empty"
        rows_by_table[name] = rows

    # FK integrity: every generated orders.customer_id exists among generated
    # customers.customer_id values (headers carry canonical names).
    customer_ids = {
        row["CustomerID"] for row in rows_by_table["customers"] if row["CustomerID"]
    }
    order_customer_ids = {
        row["CustomerID"] for row in rows_by_table["orders"] if row["CustomerID"]
    }
    assert customer_ids, "customers sample data has no customer_id values"
    assert order_customer_ids, "orders sample data has no customer_id values"
    assert order_customer_ids <= customer_ids, (
        "FK-aware generation violated: orders.customer_id values "
        f"{sorted(order_customer_ids - customer_ids)} missing from customers"
    )


def _land_typed(umf: UMF, spark: Any) -> Any:
    """Land *umf* through the reader seam and rename headers to UMF names.

    The rename mirrors raw ingestion's header resolution
    (``build_column_lookup`` / ``map_headers``): original source identifiers
    (``CustomerID``) become canonical UMF column names (``customer_id``).
    Types are untouched -- the DataFrame stays NATIVE-TYPED (JDBC-03).
    """
    source = umf.source
    df = get_reader(source).read(source, spark)
    lookup = build_column_lookup(umf)
    mapping = map_headers(df.columns, lookup)
    assert mapping, f"no headers of {umf.table_name} resolved against its UMF"
    return df.select(
        *[df[raw].alias(match.umf_column) for raw, match in mapping.items()]
    )


def _assert_staged_validation(
    discovered: dict[str, UMF], spark: Any
) -> dict[str, ValidationReport]:
    """AC6: land typed, compose suites, execute staged, report per table."""
    generator = BaselineExpectationGenerator()
    executor = GXSuiteExecutor(spark)
    reports: dict[str, ValidationReport] = {}

    landed = {name: _land_typed(discovered[name], spark) for name in AC6_TABLES}

    # Zero silent NULL-out (PARQ-02/JDBC-03): the typed orders landing keeps
    # every order_date value -- nothing was routed through a string-parse cast.
    orders_df = landed["orders"]
    from pyspark.sql.types import TimestampType

    assert isinstance(orders_df.schema["order_date"].dataType, TimestampType)
    order_dates = [
        row["order_date"] for row in orders_df.select("order_date").collect()
    ]
    assert len(order_dates) == FIXTURE_ROW_COUNTS["orders"]
    assert all(value is not None for value in order_dates), (
        "typed orders.order_date values were NULLed during landing"
    )

    for name in AC6_TABLES:
        umf = discovered[name]
        expectations = generator.generate_baseline_expectations(
            umf.model_dump(mode="json", exclude_none=True)
        )
        assert expectations, f"no baseline expectations composed for {name}"

        # SUITE-01/02 in the flow: a typed (jdbc) source composes NO
        # string-shape raw checks -- even though e.g. customers.customer_id
        # carries length=5 and orders has TIMESTAMP/DECIMAL columns that
        # would emit length/strftime/cast checks for a delimited source.
        composed_types = {exp["type"] for exp in expectations}
        assert not (composed_types & STRING_SHAPE_EXPECTATION_TYPES), (
            f"string-shape raw checks composed for typed source {name}: "
            f"{sorted(composed_types & STRING_SHAPE_EXPECTATION_TYPES)}"
        )

        df = landed[name]
        staged = executor.execute_staged(df, df, expectations)

        # Real per-expectation results: non-empty, each with a verdict drawn
        # from actually scanning the landed rows (element_count observed),
        # and no uniform silent failure.
        executed = staged.raw.results + staged.ingested.results
        assert executed, f"no expectations executed for {name}"
        assert all(
            r.expectation_type not in STRING_SHAPE_EXPECTATION_TYPES for r in executed
        )
        assert any(
            r.details.get("element_count") == FIXTURE_ROW_COUNTS[name] for r in executed
        ), f"no executed expectation observed the {name} rows"

        report = build_validation_report_from_staged_execution(
            name,
            staged,
            expectations,
            pipeline_name="northwind_e2e",
        )
        reports[name] = report
        assert report.total == len(executed)
        # The fixture data is clean: every expectation must genuinely pass
        # (a stubbed/failed-closed execution path would fail here).
        assert report.success, (
            f"validation report for {name} has failures: "
            f"{[f.__dict__ for f in report.failures()]}"
        )
        print(f"\n[US-039 AC6] {name}: {report.summary()}")
        print(json.dumps(report.as_dict(), indent=2, default=str))

    return reports


# ---------------------------------------------------------------------------
# Local Docker lane (default; skips without Docker)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    "DATABRICKS_RUNTIME_VERSION" in os.environ,
    reason="Local Docker lane; Databricks has no driver-local Docker daemon.",
)
class TestNorthwindEndToEnd:
    """US-039 acceptance flow, sequenced over one discovered-UMF session."""

    def test_ac1_ac2_ac3_discovery_flow(self, discovered):
        _assert_discovery_flow(discovered)

    def test_ac4_excel_roundtrip(self, discovered, tmp_path):
        _assert_excel_roundtrip(discovered, tmp_path / "workbooks")

    def test_ac5_fk_aware_sample_data(self, discovered, tmp_path):
        _assert_sample_data(discovered, tmp_path / "specs", tmp_path / "sample_data")

    def test_ac6_staged_validation_report(self, discovered, mssql_spark):
        reports = _assert_staged_validation(discovered, mssql_spark)
        assert set(reports) == set(AC6_TABLES)


# ---------------------------------------------------------------------------
# Databricks lane (opt-in databricks_e2e tier)
# ---------------------------------------------------------------------------


@pytest.mark.databricks_e2e
class TestNorthwindEndToEndDatabricksLane:
    """The same US-039 flow against a workspace-reachable SQL Server.

    Opt-in: gated on the shipped databricks_e2e gate (DATABRICKS_HOST &c.,
    ``tablespec.e2e.gating``) PLUS ``TABLESPEC_NORTHWIND_JDBC_URL`` -- the
    SQL Server restore on the workspace is consumer-owned (US-039), so
    tablespec only ever points at it. Skips with a precise reason whenever
    either gate is closed; never silently passes.
    """

    def test_full_flow_on_workspace(self, tmp_path):
        from tablespec.e2e.gating import databricks_e2e_availability

        reason = databricks_e2e_availability()
        if reason:
            pytest.skip(reason)
        url = os.environ.get(NORTHWIND_URL_ENV)
        if not url:
            pytest.skip(
                f"databricks_e2e Northwind lane: {NORTHWIND_URL_ENV} not set "
                "(no workspace-reachable SQL Server; the Northwind restore is "
                "consumer-owned per US-039)"
            )

        from tablespec.models.umf import JdbcSource
        from tablespec.profiling.jdbc_mapper import JdbcToUmfMapper
        from tablespec.session import get_session

        spark = get_session("tablespec-northwind-e2e")
        spec = JdbcSource(
            kind="jdbc",
            url=url,
            dbtable="INFORMATION_SCHEMA.TABLES",  # connection spec; ignored by discover()
            driver=(MSSQL_DRIVER if url.startswith("jdbc:sqlserver:") else None),
            user=os.environ.get("TABLESPEC_NORTHWIND_JDBC_USER"),
            password_secret_ref=os.environ.get(
                "TABLESPEC_NORTHWIND_JDBC_PASSWORD_SECRET_REF"
            ),
        )

        discovered = {u.table_name: u for u in JdbcToUmfMapper().discover(spec, spark)}

        _assert_discovery_flow(discovered)
        _assert_excel_roundtrip(discovered, tmp_path / "workbooks")
        _assert_sample_data(discovered, tmp_path / "specs", tmp_path / "sample_data")
        reports = _assert_staged_validation(discovered, spark)
        assert set(reports) == set(AC6_TABLES)
