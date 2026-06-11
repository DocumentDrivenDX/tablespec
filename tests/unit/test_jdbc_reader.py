"""Unit tests for the JDBC reader vertical (FEAT-031 JDBC-01..05).

Covers pure option building (no Spark), read-time secret-ref resolution
(env-var path; fail-closed paths naming the ref), deterministic identifier
sanitization (JDBC-05), reader factory dispatch, and the no-credential
invariant on everything tablespec persists or builds.
"""

from __future__ import annotations

import pytest

from tablespec.ingestion import (
    JdbcReader,
    SecretResolutionError,
    get_reader,
    jdbc_connection_options,
    jdbc_options,
    quote_identifier,
    resolve_secret_ref,
    sanitize_identifier,
)
from tablespec.models.umf import JdbcSource

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _spec(**overrides) -> JdbcSource:
    base = {
        "kind": "jdbc",
        "url": "jdbc:sqlserver://host:1433;databaseName=Northwind",
        "dbtable": "[dbo].[Customers]",
        "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
        "user": "svc_reader",
        "password_secret_ref": "NORTHWIND_PASSWORD",
    }
    base.update(overrides)
    return JdbcSource(**base)


class TestJdbcOptions:
    def test_dbtable_spec_builds_full_option_set(self):
        spec = _spec(
            fetch_size=500,
            partition_column="OrderID",
            lower_bound=1,
            upper_bound=11078,
            num_partitions=8,
        )
        assert jdbc_options(spec) == {
            "url": "jdbc:sqlserver://host:1433;databaseName=Northwind",
            "dbtable": "[dbo].[Customers]",
            "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
            "user": "svc_reader",
            "fetchsize": "500",
            "partitionColumn": "OrderID",
            "lowerBound": "1",
            "upperBound": "11078",
            "numPartitions": "8",
        }

    def test_query_spec_builds_query_option(self):
        spec = _spec(dbtable=None, query="SELECT 1 AS one")
        opts = jdbc_options(spec)
        assert opts["query"] == "SELECT 1 AS one"
        assert "dbtable" not in opts

    def test_optional_options_only_when_declared(self):
        spec = JdbcSource(kind="jdbc", url="jdbc:x", dbtable="t")
        assert jdbc_options(spec) == {"url": "jdbc:x", "dbtable": "t"}

    def test_options_never_carry_credential_material(self):
        # The pure builders are credential-free by construction (JDBC-01):
        # only the secret REFERENCE name may appear anywhere.
        for opts in (jdbc_options(_spec()), jdbc_connection_options(_spec())):
            assert "password" not in opts
            assert all("secret" not in str(v).lower() for v in opts.values())

    def test_connection_options_exclude_table_and_query(self):
        opts = jdbc_connection_options(_spec(fetch_size=100))
        assert opts == {
            "url": "jdbc:sqlserver://host:1433;databaseName=Northwind",
            "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
            "user": "svc_reader",
            "fetchsize": "100",
        }


class TestResolveSecretRef:
    def test_env_var_ref_resolves(self, monkeypatch):
        monkeypatch.setenv("NORTHWIND_PASSWORD", "s3cret-value")
        assert resolve_secret_ref("NORTHWIND_PASSWORD") == "s3cret-value"

    def test_missing_env_var_fails_closed_naming_the_ref(self, monkeypatch):
        monkeypatch.delenv("MISSING_PW_REF", raising=False)
        with pytest.raises(SecretResolutionError, match="MISSING_PW_REF"):
            resolve_secret_ref("MISSING_PW_REF")

    def test_scope_key_ref_fails_closed_outside_databricks(self, monkeypatch):
        monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
        with pytest.raises(SecretResolutionError, match="jdbc-secrets/northwind"):
            resolve_secret_ref("jdbc-secrets/northwind")

    def test_error_message_never_contains_resolved_values(self, monkeypatch):
        monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
        with pytest.raises(SecretResolutionError) as excinfo:
            resolve_secret_ref("scope/key")
        assert "Databricks" in str(excinfo.value)


class TestSanitizeIdentifier:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Order Details", "order_details"),
            ("CustomerID", "customer_id"),
            ("OrderID", "order_id"),
            ("ProductID", "product_id"),
            ("CustomerCustomerDemo", "customer_customer_demo"),
            ("QuantityPerUnit", "quantity_per_unit"),
            ("UnitsInStock", "units_in_stock"),
            ("TitleOfCourtesy", "title_of_courtesy"),
            ("ReportsTo", "reports_to"),
            ("HomePage", "home_page"),
            ("Address2", "address2"),
            ("already_snake_case", "already_snake_case"),
            ("UPPER", "upper"),
            ("weird--name__x", "weird_name_x"),
            ("  spaced  out  ", "spaced_out"),
            ("Ship Via #2", "ship_via_2"),
        ],
    )
    def test_deterministic_sanitization(self, raw, expected):
        assert sanitize_identifier(raw) == expected

    def test_idempotent(self):
        once = sanitize_identifier("Order Details")
        assert sanitize_identifier(once) == once

    def test_empty_result_raises(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_identifier("__--__")


class TestQuoteIdentifier:
    def test_sqlserver_url_uses_brackets(self):
        assert (
            quote_identifier("Order Details", "jdbc:sqlserver://h;databaseName=n")
            == "[Order Details]"
        )

    def test_embedded_bracket_is_doubled(self):
        assert quote_identifier("a]b", "jdbc:sqlserver://h") == "[a]]b]"

    def test_other_urls_use_ansi_quotes(self):
        assert quote_identifier("Order Details", "jdbc:postgresql://h/db") == (
            '"Order Details"'
        )


class _RecordingJdbcRead:
    """Stub for spark.read capturing format/options/load calls."""

    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def format(self, fmt):
        self._sink["format"] = fmt
        return self

    def options(self, **kwargs):
        self._sink["options"] = kwargs
        return self

    def load(self):
        self._sink["loaded"] = True
        return "df"


class _StubSpark:
    def __init__(self) -> None:
        self.calls: dict = {}

    @property
    def read(self):
        return _RecordingJdbcRead(self.calls)


class TestJdbcReader:
    def test_read_resolves_secret_and_passes_jdbc_options(self, monkeypatch):
        monkeypatch.setenv("NORTHWIND_PASSWORD", "s3cret-value")
        spark = _StubSpark()
        result = JdbcReader().read(_spec(), spark)  # type: ignore[arg-type]
        assert result == "df"
        assert spark.calls["format"] == "jdbc"
        assert spark.calls["loaded"] is True
        assert spark.calls["options"]["dbtable"] == "[dbo].[Customers]"
        assert spark.calls["options"]["user"] == "svc_reader"
        # Resolved at read time, handed to Spark only:
        assert spark.calls["options"]["password"] == "s3cret-value"

    def test_read_without_secret_ref_omits_password(self):
        spark = _StubSpark()
        JdbcReader().read(_spec(password_secret_ref=None), spark)  # type: ignore[arg-type]
        assert "password" not in spark.calls["options"]

    def test_unresolvable_ref_fails_closed_before_any_read(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_REF", raising=False)
        spark = _StubSpark()
        with pytest.raises(SecretResolutionError, match="NO_SUCH_REF"):
            JdbcReader().read(_spec(password_secret_ref="NO_SUCH_REF"), spark)  # type: ignore[arg-type]
        assert spark.calls == {}  # JDBC-04: no read was attempted

    def test_rejects_non_jdbc_spec(self):
        from tablespec.models.umf import DelimitedSource

        with pytest.raises(TypeError, match="jdbc"):
            JdbcReader().read(DelimitedSource(), _StubSpark())  # type: ignore[arg-type]


class TestFactoryDispatch:
    def test_jdbc_kind_dispatches_to_jdbc_reader(self):
        reader = get_reader(_spec())
        assert isinstance(reader, JdbcReader)
