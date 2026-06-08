"""Tests for CLI validation management commands: validation-remove."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.dialects import CAST_DIALECTS

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from Rich CLI output."""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _umf_with_expectations() -> dict:
    """Return a UMF dict with validation_rules expectations."""
    return {
        "version": "1.0",
        "table_name": "TestTable",
        "columns": [
            {"name": "id", "data_type": "INTEGER"},
            {"name": "name", "data_type": "VARCHAR"},
        ],
        "validation_rules": {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                    "meta": {"severity": "critical"},
                },
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"column": "name", "regex": "^[A-Z]"},
                    "meta": {"severity": "warning"},
                },
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"column": "id", "regex": "^\\d+$"},
                    "meta": {"severity": "info"},
                },
            ]
        },
    }


def _write_umf(tmp_path: Path) -> Path:
    umf_file = tmp_path / "test.json"
    umf_file.write_text(json.dumps(_umf_with_expectations()))
    return umf_file


def _load_umf(path: Path) -> dict:
    return json.loads(path.read_text())


def _normalize_output(text: str) -> str:
    """Collapse CLI output to make wrapped help text easy to assert against."""
    return " ".join(text.split())


def _umf_for_emit() -> dict:
    """A minimal single-table UMF the dbt emitter can render into a project."""
    return {
        "version": "1.0",
        "table_name": "metrics",
        "primary_key": ["metric_id"],
        "ingestion": {"mode": "incremental", "order_by": ["_load_ts"]},
        "columns": [
            {
                "name": "metric_id",
                "data_type": "INTEGER",
                "nullable": {"default": False},
            },
            {"name": "as_of_date", "data_type": "DATE", "format": "YYYYMMDD"},
            {"name": "label", "data_type": "VARCHAR", "length": 32},
        ],
    }


class TestEmitDialectOption:
    """Regression coverage for the public `emit --dialect` contract."""

    def test_help_explains_databricks_alias(self) -> None:
        result = runner.invoke(app, ["emit", "--help"])
        assert result.exit_code == 0, result.output

        assert re.search(
            r"Cast dialect for emitted.*duckdb.*spark.*databricks",
            result.output,
            re.S,
        )
        assert re.search(
            r"databricks.*Databricks-facing.*alias.*Spark-family.*cast SQL",
            result.output,
            re.S,
        )

    def test_invalid_value_lists_canonical_choices(self, tmp_path: Path) -> None:
        umf_file = tmp_path / "metrics.json"
        umf_file.write_text(json.dumps(_umf_for_emit()))
        out_dir = tmp_path / "project"

        result = runner.invoke(
            app,
            [
                "emit",
                str(umf_file),
                str(out_dir),
                "--dialect",
                "postgres",
            ],
        )
        assert result.exit_code != 0

        output = _normalize_output(result.output)
        for value in CAST_DIALECTS:
            assert value in output
        assert "Databricks-facing alias" not in output


class TestEmitBackend:
    """`tablespec emit --backend dbt` produces a runnable dbt project dir."""

    @pytest.mark.no_spark
    def test_emit_dbt_writes_project(self, tmp_path: Path) -> None:
        umf_file = tmp_path / "metrics.json"
        umf_file.write_text(json.dumps(_umf_for_emit()))
        out_dir = tmp_path / "project"

        result = runner.invoke(
            app,
            ["emit", str(umf_file), str(out_dir), "--backend", "dbt"],
        )
        assert result.exit_code == 0, result.output
        # The emitted project carries the model + scaffolding.
        assert (out_dir / "dbt_project.yml").exists()
        assert (out_dir / "models" / "metrics.sql").exists()
        assert (out_dir / "models" / "schema.yml").exists()
        assert (out_dir / "profiles.yml").exists()
        assert "Emitted" in _strip_ansi(result.output)

    @pytest.mark.no_spark
    def test_emit_unknown_backend_errors(self, tmp_path: Path) -> None:
        umf_file = tmp_path / "metrics.json"
        umf_file.write_text(json.dumps(_umf_for_emit()))

        result = runner.invoke(
            app,
            ["emit", str(umf_file), str(tmp_path / "p"), "--backend", "nope"],
        )
        assert result.exit_code == 1, result.output
        assert "Unknown emitter backend" in _strip_ansi(result.output)

    @pytest.mark.no_spark
    @pytest.mark.slow
    def test_emit_dbt_run(self, tmp_path: Path) -> None:
        """`emit --run` emits AND runs the project via dbt-duckdb (gated on dbt)."""
        import duckdb as _duckdb

        pytest.importorskip("dbt", reason="dbt-core required for --run")
        pytest.importorskip("dbt.adapters.duckdb", reason="dbt-duckdb required")

        umf_file = tmp_path / "metrics.json"
        umf_file.write_text(json.dumps(_umf_for_emit()))
        out_dir = tmp_path / "project"

        # The model reads from raw_metrics; create it before --run so dbt build
        # has a source to materialize from.
        db = out_dir / "tablespec.duckdb"
        out_dir.mkdir(parents=True, exist_ok=True)
        con = _duckdb.connect(str(db))
        try:
            con.execute(
                'CREATE TABLE raw_metrics ("metric_id" VARCHAR, "as_of_date" VARCHAR, '
                '"label" VARCHAR, "_source_file" VARCHAR, "_load_ts" TIMESTAMP)'
            )
            con.execute(
                "INSERT INTO raw_metrics VALUES "
                "('1','20240101','alpha','s.csv', TIMESTAMP '2024-01-01 00:00:00')"
            )
        finally:
            con.close()

        result = runner.invoke(
            app,
            ["emit", str(umf_file), str(out_dir), "--backend", "dbt", "--run"],
        )
        assert result.exit_code == 0, result.output
        assert "dbt build succeeded" in _strip_ansi(result.output)


class TestValidationRemove:
    def test_remove_by_type_and_column(self, tmp_path: Path) -> None:
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            [
                "validation-remove",
                str(umf_file),
                "--type",
                "expect_column_values_to_match_regex",
                "--column",
                "name",
            ],
        )
        assert result.exit_code == 0
        assert "Removed" in result.output
        assert "1 expectation" in _strip_ansi(result.output)

        data = _load_umf(umf_file)
        exps = data["expectations"]["expectations"]
        assert len(exps) == 2
        # The regex on "name" should be gone, regex on "id" should remain
        regex_cols = [e["kwargs"]["column"] for e in exps if "regex" in e["type"]]
        assert "name" not in regex_cols
        assert "id" in regex_cols

    def test_remove_by_type_all_columns(self, tmp_path: Path) -> None:
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            [
                "validation-remove",
                str(umf_file),
                "--type",
                "expect_column_values_to_match_regex",
            ],
        )
        assert result.exit_code == 0
        assert "2 expectation" in _strip_ansi(result.output)

        data = _load_umf(umf_file)
        exps = data["expectations"]["expectations"]
        assert len(exps) == 1
        assert exps[0]["type"] == "expect_column_values_to_not_be_null"

    def test_remove_no_match(self, tmp_path: Path) -> None:
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            [
                "validation-remove",
                str(umf_file),
                "--type",
                "expect_column_values_to_be_unique",
            ],
        )
        assert result.exit_code == 0
        assert "No matching" in result.output


class TestRemoveExpectationFunction:
    """Test the pure function directly."""

    def test_remove_specific(self) -> None:
        from tests.builders import UMFBuilder

        from tablespec.authoring.mutations import remove_expectation
        from tablespec.models.umf import Expectation, ExpectationMeta, ExpectationSuite

        umf = (
            UMFBuilder("test").column("id", "INTEGER").column("name", "VARCHAR").build()
        )
        suite = ExpectationSuite(
            expectations=[
                Expectation(
                    type="expect_column_values_to_not_be_null",
                    kwargs={"column": "id"},
                    meta=ExpectationMeta(stage="raw", severity="critical"),
                ),
                Expectation(
                    type="expect_column_values_to_match_regex",
                    kwargs={"column": "name", "regex": ".*"},
                    meta=ExpectationMeta(stage="raw", severity="warning"),
                ),
            ]
        )
        umf = umf.model_copy(update={"expectations": suite})
        updated, count = remove_expectation(
            umf, "expect_column_values_to_not_be_null", "id"
        )
        assert count == 1
        assert len(updated.expectations.expectations) == 1

    def test_remove_returns_zero_when_no_match(self) -> None:
        from tests.builders import UMFBuilder

        from tablespec.authoring.mutations import remove_expectation

        umf = UMFBuilder("test").column("id", "INTEGER").build()
        updated, count = remove_expectation(umf, "nonexistent_type")
        assert count == 0
