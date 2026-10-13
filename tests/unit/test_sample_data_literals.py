"""Regression coverage for constant inline values and safe warehouse errors."""

from datetime import date, datetime
import re
from types import SimpleNamespace

import pytest
from hypothesis import given, strategies as st

from tablespec.sample_data.sink import literal, load_dataset, WarehouseSQLSink
from tests.unit.test_legal_sample_data import dataset, FakeSink

pytestmark = pytest.mark.no_spark


def test_loader_values_use_only_constants(tmp_path):
    data = dataset(tmp_path)
    try:
        sink = FakeSink()
        load_dataset(data, "sample.legal", sink)
        for sql in sink.statements:
            if sql.startswith("INSERT INTO"):
                values = sql.split(" VALUES ", 1)[1]
                without_strings = re.sub(r"'(?:\\.|[^'\\])*'", "''", values)
                assert not re.search(r"\b[a-z_]\w*\s*\(", without_strings, re.I), sql
                if "DATE'" in values:
                    assert "decode(" not in without_strings
        assert any("DATE'" in sql for sql in sink.statements)
    finally:
        data.close()


def test_temporal_literals_and_unsupported_characters():
    assert literal("2026-10-08", "DATE") == "DATE'2026-10-08'"
    assert literal(date(2026, 10, 8)) == "DATE'2026-10-08'"
    assert (
        literal(datetime(2026, 10, 8, 12, 30), "TIMESTAMP")
        == "TIMESTAMP'2026-10-08 12:30:00'"
    )
    for value in ["\ud800", "\x01", "\x7f"]:
        with pytest.raises(ValueError):
            literal(value)


@given(st.text(alphabet=st.sampled_from(["a", "'", "\\", "\n", "\t", "\x00", "😀"])))
def test_strings_never_require_functions(value):
    sql = literal(value)
    assert sql.startswith("'") and sql.endswith("'")
    assert "\x00" not in sql and "\n" not in sql and "\t" not in sql


@pytest.mark.parametrize(
    "error",
    [
        None,
        SimpleNamespace(
            error_code="BAD_REQUEST",
            message='[INVALID_INLINE_TABLE.CANNOT_EVALUATE_EXPRESSION_IN_INLINE_TABLE] Cannot evaluate expression "fabricated row" in inline table definition. SQLSTATE: 42000',
        ),
    ],
)
def test_warehouse_failure_details(error):
    status = SimpleNamespace(state="FAILED", error=error)
    client = SimpleNamespace(
        statement_execution=SimpleNamespace(
            execute_statement=lambda **kwargs: SimpleNamespace(status=status)
        )
    )
    sink = WarehouseSQLSink("local-test", "local-test", client=client)
    with pytest.raises(RuntimeError) as exc:
        sink.execute("INSERT INTO sample VALUES ('fabricated row')")
    message = str(exc.value)
    assert "FAILED" in message
    assert "fabricated row" not in message and "INSERT" not in message
    assert len(message) <= 512
    if error:
        assert "BAD_REQUEST" in message and "42000" in message
        assert "CANNOT_EVALUATE_EXPRESSION_IN_INLINE_TABLE" in message
    else:
        assert "no safe error details" in message


def test_remote_error_redacts_statement_values_hosts_and_generated_secret():
    from tablespec.sample_data.sink import warehouse_failure

    secret = "d" + "api" + "x" * 32
    raw = (
        'Cannot evaluate expression "private fabricated narrative". INSERT INTO table VALUES (123). https://warehouse.example.invalid Bearer '
        + secret
        + " "
        + "unexpected" * 1000
    )
    status = SimpleNamespace(
        state="FAILED",
        sql_state="42000",
        error=SimpleNamespace(error_code="BAD_REQUEST", message=raw),
    )
    result = warehouse_failure(status)
    assert "42000" in result and "BAD_REQUEST" in result
    assert len(result) <= 512
    for value in [
        secret,
        "warehouse.example.invalid",
        "private fabricated narrative",
        "123",
        "INSERT INTO",
    ]:
        assert value not in result


def test_locked_sdk_cli_auth_uses_requested_profile():
    from databricks.sdk.credentials_provider import CliVersion, DatabricksCliTokenSource

    # Pure command construction only: no Config auth discovery or CLI execution.
    command = DatabricksCliTokenSource._build_core_cli_command(
        "databricks",
        SimpleNamespace(profile="local-sample", host=None),
        CliVersion(0, 207, 1),
    )
    assert command == ["databricks", "auth", "token", "--profile", "local-sample"]


def test_sdk_client_receives_profile_without_credentials(monkeypatch):
    import databricks.sdk

    calls = []
    monkeypatch.setattr(
        databricks.sdk,
        "WorkspaceClient",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(),
    )
    WarehouseSQLSink("local-test", "local-sample")
    assert calls == [{"profile": "local-sample"}]


def test_error_withholds_unquoted_submitted_value_even_if_diagnostic_words():
    from tablespec.sample_data.sink import warehouse_failure

    status = SimpleNamespace(
        state="FAILED",
        error=SimpleNamespace(message="invalid argument: cannot evaluate expression"),
    )
    result = warehouse_failure(
        status, "INSERT INTO t VALUES ('cannot evaluate expression')"
    )
    assert "cannot evaluate expression" not in result
    assert "invalid argument" in result
