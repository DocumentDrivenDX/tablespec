"""Docker-gated SQL Server 2022 lane for JDBC discovery + reading (FEAT-031).

US-039's local test scenario: a SQL Server container loaded with a
Northwind-faithful fixture (``tests/fixtures/northwind/northwind.sql``,
executed INSIDE the container via ``docker exec sqlcmd`` -- no Python DB
drivers, per the operator decision on DISC-01). The suite SKIPS (never fails)
when Docker is unavailable or the image cannot be pulled. The container /
Spark / discovery fixtures live in ``tests/integration/conftest.py`` and are
shared with the US-039 end-to-end run (``test_northwind_e2e.py``).

Asserts the US-039 seeds: 13 base tables discovered; ``order_details``
sanitization + FKs (``order_id -> orders.order_id``,
``product_id -> products.product_id``); ``customers.customer_id`` CHAR(5)
NOT NULL; ``orders.customer_id -> customers.customer_id``; no credential
material in any emitted UMF; every UMF passes ``tablespec validate``; and
``JdbcReader`` actually reads rows from ``customers``.

All connectivity is Spark's JDBC connector: the test session pulls the mssql
driver via ``spark.jars.packages`` (JDBC-02/DISC-01).
"""

from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("pyspark", reason="PySpark required for the JDBC lane")

from tablespec.ingestion import JdbcReader, get_reader  # noqa: E402
from tablespec.models.umf import JdbcSource  # noqa: E402

from tests.integration.conftest import (  # noqa: E402
    EXPECTED_TABLES,
    SA_PASSWORD,
    SECRET_ENV_VAR,
)

pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.slow,
    pytest.mark.skipif(
        "DATABRICKS_RUNTIME_VERSION" in os.environ,
        reason="Local Docker lane; Databricks has no driver-local Docker daemon.",
    ),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


class TestNorthwindDiscovery:
    def test_discovers_all_13_base_tables(self, discovered):
        assert set(discovered) == EXPECTED_TABLES

    def test_order_details_sanitized_with_original_preserved(self, discovered):
        """US-039-AC2: canonical names + original identifier at the read boundary."""
        umf = discovered["order_details"]
        assert umf.canonical_name == "Order Details"
        assert isinstance(umf.source, JdbcSource)
        assert umf.source.dbtable == "[dbo].[Order Details]"
        data_columns = [c for c in umf.columns if not c.name.startswith("meta_")]
        assert [c.name for c in data_columns] == [
            "order_id",
            "product_id",
            "unit_price",
            "quantity",
            "discount",
        ]
        assert [c.canonical_name for c in data_columns] == [
            "OrderID",
            "ProductID",
            "UnitPrice",
            "Quantity",
            "Discount",
        ]

    def test_order_details_keys(self, discovered):
        umf = discovered["order_details"]
        assert umf.primary_key == ["order_id", "product_id"]
        fks = {
            (fk.column, fk.references_table, fk.references_column)
            for fk in (umf.relationships.foreign_keys or [])
        }
        assert ("order_id", "orders", "order_id") in fks
        assert ("product_id", "products", "product_id") in fks

    def test_customers_customer_id_is_char5_not_null(self, discovered):
        col = {c.name: c for c in discovered["customers"].columns}["customer_id"]
        assert col.canonical_name == "CustomerID"
        assert col.data_type == "CHAR"
        assert col.length == 5
        assert col.nullable is not None
        assert col.nullable.model_dump().get("default") is False

    def test_orders_fk_to_customers(self, discovered):
        fks = {
            (fk.column, fk.references_table, fk.references_column)
            for fk in (discovered["orders"].relationships.foreign_keys or [])
        }
        assert ("customer_id", "customers", "customer_id") in fks

    def test_orders_pk_and_typed_columns(self, discovered):
        umf = discovered["orders"]
        assert umf.primary_key == ["order_id"]
        cols = {c.name: c for c in umf.columns}
        assert cols["order_date"].data_type == "TIMESTAMP"  # datetime
        assert cols["freight"].data_type == "DECIMAL"  # money
        assert cols["freight"].precision == 19
        assert cols["freight"].scale == 4

    def test_no_credential_material_in_any_emitted_umf(self, discovered):
        """DISC-02/JDBC-01: secret REFERENCES only; the SA password never appears."""
        for umf in discovered.values():
            serialized = json.dumps(umf.model_dump(mode="json", exclude_none=True))
            assert SA_PASSWORD not in serialized
            assert isinstance(umf.source, JdbcSource)
            assert umf.source.password_secret_ref == SECRET_ENV_VAR

    def test_every_emitted_umf_passes_tablespec_validate(self, discovered, tmp_path):
        """DISC-02: discovered specs pass ``tablespec validate`` unmodified."""
        from typer.testing import CliRunner

        from tablespec.cli import app

        runner = CliRunner()
        for name, umf in discovered.items():
            spec_file = tmp_path / f"{name}.json"
            spec_file.write_text(
                json.dumps(umf.model_dump(mode="json", exclude_none=True), indent=2)
            )
            result = runner.invoke(app, ["validate", str(spec_file)])
            assert result.exit_code == 0, (
                f"tablespec validate failed for {name}:\n{result.output}"
            )

    def test_jdbc_reader_reads_rows_from_customers(self, discovered, mssql_spark):
        """JDBC-02: the reader seam reads real rows via Spark's JDBC connector."""
        source = discovered["customers"].source
        reader = get_reader(source)
        assert isinstance(reader, JdbcReader)
        rows = reader.read(source, mssql_spark).collect()
        assert len(rows) == 3
        assert {r["CustomerID"] for r in rows} == {"ALFKI", "ANATR", "ANTON"}

    def test_unresolvable_secret_ref_fails_closed_before_read(
        self, discovered, mssql_spark, monkeypatch
    ):
        """JDBC-04 against a real session: error names the ref; no read happens."""
        from tablespec.ingestion import SecretResolutionError

        monkeypatch.delenv("TABLESPEC_NO_SUCH_SECRET", raising=False)
        source = discovered["customers"].source
        assert isinstance(source, JdbcSource)
        broken = source.model_copy(
            update={"password_secret_ref": "TABLESPEC_NO_SUCH_SECRET"}
        )
        with pytest.raises(SecretResolutionError, match="TABLESPEC_NO_SUCH_SECRET"):
            JdbcReader().read(broken, mssql_spark)
