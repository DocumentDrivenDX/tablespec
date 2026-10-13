"""Tests for CLI apply-response command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tablespec.cli import app

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _write_umf(tmp_path: Path) -> Path:
    path = tmp_path / "table.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "table_name": "TestTable",
                "columns": [{"name": "id", "data_type": "INTEGER"}],
                "validation_rules": {
                    "expectations": [
                        {
                            "type": "expect_column_values_to_not_be_null",
                            "kwargs": {"column": "id"},
                        }
                    ]
                },
            }
        )
    )
    return path


def _write_response(tmp_path: Path) -> Path:
    path = tmp_path / "response.json"
    path.write_text(
        json.dumps(
            [
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"column": "id", "regex": "^\\d+$"},
                }
            ]
        )
    )
    return path


def test_apply_response_persists_expectation_suite(tmp_path: Path) -> None:
    umf_file = _write_umf(tmp_path)
    response_file = _write_response(tmp_path)

    result = runner.invoke(app, ["apply-response", str(umf_file), str(response_file)])

    assert result.exit_code == 0
    assert "Added:" in result.output

    updated = json.loads(umf_file.read_text())
    assert "expectations" in updated
    assert "validation_rules" not in updated
    expectations = updated["expectations"]["expectations"]
    assert len(expectations) == 2
    assert expectations[1]["meta"]["generated_from"] == "llm"


def test_apply_response_dry_run_does_not_persist(tmp_path: Path) -> None:
    umf_file = _write_umf(tmp_path)
    response_file = _write_response(tmp_path)

    result = runner.invoke(
        app, ["apply-response", str(umf_file), str(response_file), "--dry-run"]
    )

    assert result.exit_code == 0
    assert "Dry run" in result.output

    updated = json.loads(umf_file.read_text())
    assert "validation_rules" in updated
    assert "expectations" not in updated
