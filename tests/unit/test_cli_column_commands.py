# SPDX-License-Identifier: MIT OR Apache-2.0
"""Tests for CLI column mutation commands: column-add, column-remove, column-modify, column-rename."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tablespec.cli import app

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _minimal_umf() -> dict:
    """Return a minimal valid UMF dict with two columns."""
    return {
        "version": "1.0",
        "table_name": "TestTable",
        "columns": [
            {
                "name": "id",
                "data_type": "INTEGER",
            },
            {
                "name": "name",
                "data_type": "VARCHAR",
                "length": 100,
            },
        ],
    }


def _write_umf(tmp_path: Path) -> Path:
    """Write a minimal UMF JSON file and return its path."""
    umf_file = tmp_path / "test.json"
    umf_file.write_text(json.dumps(_minimal_umf()))
    return umf_file


def _load_umf(path: Path) -> dict:
    """Load a UMF JSON file and return parsed dict."""
    return json.loads(path.read_text())


class TestColumnAdd:
    """Test column-add command."""

    def test_add_column_success(self, tmp_path: Path) -> None:
        """Adding a new column writes it to the UMF file."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-add", str(umf_file), "--name", "age", "--type", "INTEGER"],
        )
        assert result.exit_code == 0
        assert "Added" in result.output
        assert "age" in result.output

        data = _load_umf(umf_file)
        col_names = [c["name"] for c in data["columns"]]
        assert "age" in col_names

    def test_add_duplicate_column_errors(self, tmp_path: Path) -> None:
        """Adding a column that already exists exits with error."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-add", str(umf_file), "--name", "id", "--type", "INTEGER"],
        )
        assert result.exit_code != 0
        assert "already exists" in result.output


class TestColumnRemove:
    """Test column-remove command."""

    def test_remove_column_success(self, tmp_path: Path) -> None:
        """Removing an existing column removes it from the UMF file."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-remove", str(umf_file), "--name", "name"],
        )
        assert result.exit_code == 0
        assert "Removed" in result.output

        data = _load_umf(umf_file)
        col_names = [c["name"] for c in data["columns"]]
        assert "name" not in col_names
        assert "id" in col_names

    def test_remove_nonexistent_column_errors(self, tmp_path: Path) -> None:
        """Removing a column that doesn't exist exits with error."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-remove", str(umf_file), "--name", "nonexistent"],
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestColumnModify:
    """Test column-modify command."""

    def test_modify_data_type(self, tmp_path: Path) -> None:
        """Modifying a column's data_type updates the UMF file."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-modify", str(umf_file), "--name", "id", "--type", "FLOAT"],
        )
        assert result.exit_code == 0
        assert "Modified" in result.output

        data = _load_umf(umf_file)
        id_col = next(c for c in data["columns"] if c["name"] == "id")
        assert id_col["data_type"] == "FLOAT"

    def test_modify_no_changes_exits_cleanly(self, tmp_path: Path) -> None:
        """Specifying no changes exits with code 0."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-modify", str(umf_file), "--name", "id"],
        )
        assert result.exit_code == 0
        assert "No changes" in result.output


class TestColumnRename:
    """Test column-rename command."""

    def test_rename_column_success(self, tmp_path: Path) -> None:
        """Renaming a column updates the name in the UMF file."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            ["column-rename", str(umf_file), "--from", "name", "--to", "full_name"],
        )
        assert result.exit_code == 0
        assert "Renamed" in result.output

        data = _load_umf(umf_file)
        col_names = [c["name"] for c in data["columns"]]
        assert "full_name" in col_names
        assert "name" not in col_names

    def test_rename_with_keep_alias(self, tmp_path: Path) -> None:
        """Renaming with --keep-alias preserves the old name as an alias."""
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(
            app,
            [
                "column-rename",
                str(umf_file),
                "--from",
                "name",
                "--to",
                "full_name",
                "--keep-alias",
            ],
        )
        assert result.exit_code == 0
        assert "alias" in result.output

        data = _load_umf(umf_file)
        renamed_col = next(c for c in data["columns"] if c["name"] == "full_name")
        assert "name" in renamed_col.get("aliases", [])
