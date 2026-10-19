# SPDX-License-Identifier: MIT OR Apache-2.0
"""Tests for the UMF TUI explorer.

Tests the data-loading and formatting helpers directly (no Textual app needed),
and basic app instantiation when textual is available.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

# Skip entire module if textual is not installed
textual = pytest.importorskip("textual", reason="textual not installed")


from tablespec.tui import (
    UMFExplorer,
    _format_column_detail,
    _matches_search,
    _nullable_badge,
    load_umfs_from_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_UMF_YAML = textwrap.dedent("""\
    table_name: Test_Table
    version: "1.0"
    description: A test table
    columns:
      - name: claim_id
        data_type: INTEGER
        description: Unique identifier
        nullable:
          MD: false
          MP: false
      - name: patient_name
        data_type: VARCHAR
        description: Full name of the patient
        nullable:
          MD: true
          MP: false
        domain_type: person_name
        length: 100
      - name: service_date
        data_type: DATE
        description: Date of service
        format: YYYY-MM-DD
        nullable:
          MD: false
          MP: false
""")


@pytest.fixture()
def umf_yaml_file(tmp_path: Path) -> Path:
    """Write a sample UMF YAML file and return its path."""
    p = tmp_path / "test_table.yaml"
    p.write_text(SAMPLE_UMF_YAML)
    return p


@pytest.fixture()
def umf_yaml_dir(tmp_path: Path) -> Path:
    """Write multiple UMF YAML files in a directory."""
    d = tmp_path / "tables"
    d.mkdir()
    (d / "table_a.yaml").write_text(SAMPLE_UMF_YAML)
    (d / "table_b.yaml").write_text(
        textwrap.dedent("""\
        table_name: Other_Table
        version: "1.0"
        columns:
          - name: id
            data_type: INTEGER
            description: Primary key
          - name: status
            data_type: VARCHAR
            description: Record status
            domain_type: status_code
    """)
    )
    # Non-UMF file (no columns key) should be ignored
    (d / "config.yaml").write_text("setting: value\n")
    return d


# ---------------------------------------------------------------------------
# Tests: load_umfs_from_path
# ---------------------------------------------------------------------------


class TestLoadUmfs:
    def test_load_single_file(self, umf_yaml_file: Path) -> None:
        umfs = load_umfs_from_path(umf_yaml_file)
        assert len(umfs) == 1
        assert umfs[0]["table_name"] == "Test_Table"
        assert len(umfs[0]["columns"]) == 3
        assert umfs[0]["_source_path"] == str(umf_yaml_file)

    def test_load_directory(self, umf_yaml_dir: Path) -> None:
        umfs = load_umfs_from_path(umf_yaml_dir)
        assert len(umfs) == 2
        names = {u["table_name"] for u in umfs}
        assert names == {"Test_Table", "Other_Table"}

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        umfs = load_umfs_from_path(tmp_path / "nope.yaml")
        assert umfs == []

    def test_load_empty_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        umfs = load_umfs_from_path(d)
        assert umfs == []


# ---------------------------------------------------------------------------
# Tests: nullable badge
# ---------------------------------------------------------------------------


class TestNullableBadge:
    def test_none_nullable(self) -> None:
        assert _nullable_badge({}) == "nullable"

    def test_all_not_null(self) -> None:
        assert _nullable_badge({"nullable": {"MD": False, "MP": False}}) == "NOT NULL"

    def test_all_nullable(self) -> None:
        assert _nullable_badge({"nullable": {"MD": True, "MP": True}}) == "nullable"

    def test_mixed(self) -> None:
        badge = _nullable_badge({"nullable": {"MD": True, "MP": False}})
        assert "MD:Y" in badge
        assert "MP:N" in badge


# ---------------------------------------------------------------------------
# Tests: column detail formatting
# ---------------------------------------------------------------------------


class TestFormatColumnDetail:
    def test_basic_fields(self) -> None:
        col = {"name": "claim_id", "data_type": "INTEGER", "description": "Unique ID"}
        detail = _format_column_detail(col)
        assert "claim_id" in detail
        assert "INTEGER" in detail
        assert "Unique ID" in detail

    def test_profiling_data(self) -> None:
        col = {
            "name": "x",
            "data_type": "INTEGER",
            "profiling": {"completeness": 0.95, "approximate_num_distinct": 100},
        }
        detail = _format_column_detail(col)
        assert "95.0%" in detail
        assert "~100" in detail

    def test_domain_type_shown(self) -> None:
        col = {"name": "state", "data_type": "VARCHAR", "domain_type": "us_state_code"}
        detail = _format_column_detail(col)
        assert "us_state_code" in detail


# ---------------------------------------------------------------------------
# Tests: search matching
# ---------------------------------------------------------------------------


class TestMatchesSearch:
    def test_match_name(self) -> None:
        col = {"name": "claim_id", "data_type": "INTEGER"}
        assert _matches_search(col, "claim")
        assert not _matches_search(col, "patient")

    def test_match_description(self) -> None:
        col = {"name": "x", "data_type": "VARCHAR", "description": "Patient full name"}
        assert _matches_search(col, "patient")

    def test_match_domain_type(self) -> None:
        col = {"name": "x", "data_type": "VARCHAR", "domain_type": "us_state_code"}
        assert _matches_search(col, "state")

    def test_match_data_type(self) -> None:
        col = {"name": "x", "data_type": "DECIMAL"}
        assert _matches_search(col, "decimal")

    def test_case_insensitive(self) -> None:
        col = {"name": "ClaimID", "data_type": "INTEGER"}
        assert _matches_search(col, "claimid")


# ---------------------------------------------------------------------------
# Tests: UMFExplorer instantiation
# ---------------------------------------------------------------------------


class TestExplorerInstantiation:
    def test_can_instantiate(self, tmp_path: Path) -> None:
        explorer = UMFExplorer(tmp_path)
        assert explorer._path == tmp_path

    def test_accepts_file_path(self, umf_yaml_file: Path) -> None:
        explorer = UMFExplorer(umf_yaml_file)
        assert explorer._path == umf_yaml_file
