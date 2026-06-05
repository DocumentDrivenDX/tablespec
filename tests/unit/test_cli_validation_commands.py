"""Tests for CLI validation management commands: validation-remove."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tablespec.cli import app

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

        umf = UMFBuilder("test").column("id", "INTEGER").column("name", "VARCHAR").build()
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
        updated, count = remove_expectation(umf, "expect_column_values_to_not_be_null", "id")
        assert count == 1
        assert len(updated.expectations.expectations) == 1

    def test_remove_returns_zero_when_no_match(self) -> None:
        from tests.builders import UMFBuilder

        from tablespec.authoring.mutations import remove_expectation

        umf = UMFBuilder("test").column("id", "INTEGER").build()
        updated, count = remove_expectation(umf, "nonexistent_type")
        assert count == 0
