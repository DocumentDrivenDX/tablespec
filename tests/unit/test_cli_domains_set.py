"""Tests for CLI domains-set command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tablespec.cli import app

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _minimal_umf() -> dict:
    return {
        "version": "1.0",
        "table_name": "TestTable",
        "columns": [
            {"name": "gender_cd", "data_type": "VARCHAR"},
            {"name": "state_cd", "data_type": "VARCHAR"},
        ],
    }


def _write_umf(tmp_path: Path) -> Path:
    umf_file = tmp_path / "test.json"
    umf_file.write_text(json.dumps(_minimal_umf()))
    return umf_file


class TestDomainsSet:
    def test_set_valid_domain_type(self, tmp_path: Path) -> None:
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["domains-set", str(umf_file), "--column", "gender_cd", "--type", "gender"],
        )
        assert result.exit_code == 0
        assert "Set" in result.output
        assert "gender" in result.output

        data = json.loads(umf_file.read_text())
        col = next(c for c in data["columns"] if c["name"] == "gender_cd")
        assert col["domain_type"] == "gender"

    def test_set_invalid_domain_type(self, tmp_path: Path) -> None:
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            [
                "domains-set",
                str(umf_file),
                "--column",
                "gender_cd",
                "--type",
                "nonexistent_type",
            ],
        )
        assert result.exit_code != 0
        assert "Unknown domain type" in result.output

    def test_set_nonexistent_column(self, tmp_path: Path) -> None:
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            [
                "domains-set",
                str(umf_file),
                "--column",
                "missing_col",
                "--type",
                "gender",
            ],
        )
        assert result.exit_code != 0
        assert "not found" in result.output
