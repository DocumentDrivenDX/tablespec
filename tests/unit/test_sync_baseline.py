"""Tests for sync_baseline module - sync logic, conflict detection, metadata columns."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from tablespec.ingestion.constants import PROVENANCE_COLUMNS
from tablespec.models import UMF, UMFColumn
from tablespec.sync_baseline import (
    METADATA_COLUMN_DEFINITIONS,
    BaselineSyncer,
    ConflictDetail,
    SyncResult,
    ValidationAdded,
    ValidationRemoved,
    ValidationSeverityPreserved,
    ValidationUpgraded,
    get_metadata_column_definitions,
)
from tablespec.umf_loader import UMFFormat, UMFLoader

pytestmark = pytest.mark.fast


# ============================================================================
# SyncResult tests
# ============================================================================


class TestSyncResult:
    """Test SyncResult dataclass and its methods."""

    def test_has_conflicts_false_when_empty(self):
        result = SyncResult(table_name="test")
        assert result.has_conflicts is False

    def test_has_conflicts_true_when_conflicts_exist(self):
        result = SyncResult(table_name="test")
        result.conflicts.append(
            ConflictDetail(
                column_name="col",
                rule_type="expect_column_to_exist",
                canonical_kwargs={},
                existing_kwargs={},
                difference="different",
            )
        )
        assert result.has_conflicts is True

    def test_summary_lines_minimal(self):
        result = SyncResult(table_name="my_table")
        lines = result.summary_lines()
        assert lines == ["my_table:"]

    def test_summary_lines_with_columns(self):
        result = SyncResult(
            table_name="my_table",
            columns_added=2,
            columns_updated=1,
            columns_skipped=3,
        )
        lines = result.summary_lines()
        assert "my_table:" in lines
        assert any("2 added" in line for line in lines)
        assert any("1 updated" in line for line in lines)
        assert any("3 skipped" in line for line in lines)

    def test_summary_lines_with_validations(self):
        result = SyncResult(
            table_name="my_table",
            validations_added=5,
            validations_upgraded=2,
            validations_conflicts=1,
            validations_severity_preserved=3,
        )
        lines = result.summary_lines()
        validation_line = [line for line in lines if "Validations:" in line]
        assert len(validation_line) == 1
        assert "5 added" in validation_line[0]
        assert "2 upgraded" in validation_line[0]
        assert "1 conflicts" in validation_line[0]
        assert "3 custom severities preserved" in validation_line[0]

    def test_format_validation_rule_with_kwargs(self):
        formatted = SyncResult.format_validation_rule(
            "expect_column_values_to_match_regex",
            {"column": "col1", "regex": "^[A-Z]{2}$"},
        )
        # Column kwarg should be excluded from display (but "column" in rule type name is fine)
        assert "column=" not in formatted
        assert "regex=^[A-Z]{2}$" in formatted

    def test_format_validation_rule_no_kwargs(self):
        formatted = SyncResult.format_validation_rule(
            "expect_column_to_exist",
            {"column": "col1"},
        )
        # Only column in kwargs, which gets removed
        assert formatted == "expect_column_to_exist"

    def test_format_validation_rule_truncates_long_values(self):
        long_value = "x" * 100
        formatted = SyncResult.format_validation_rule(
            "expect_column_values_to_be_in_set",
            {"column": "col1", "value_set": long_value},
        )
        assert "..." in formatted


# ============================================================================
# ConflictDetail / ValidationSyncChange dataclass tests
# ============================================================================


class TestDataclasses:
    """Test sync-related dataclasses."""

    def test_conflict_detail(self):
        cd = ConflictDetail(
            column_name="col",
            rule_type="expect_column_to_exist",
            canonical_kwargs={"column": "col"},
            existing_kwargs={"column": "col", "extra": True},
            difference="Different kwargs keys: {'extra'}",
        )
        assert cd.column_name == "col"
        assert cd.difference == "Different kwargs keys: {'extra'}"

    def test_validation_added(self):
        va = ValidationAdded(
            column_name="col",
            rule_type="expect_column_to_exist",
            kwargs={"column": "col"},
            generated_from="baseline",
        )
        assert va.generated_from == "baseline"

    def test_validation_removed(self):
        vr = ValidationRemoved(
            column_name="col",
            rule_type="expect_column_to_exist",
            kwargs={"column": "col"},
            generated_from="baseline",
        )
        assert vr.rule_type == "expect_column_to_exist"

    def test_validation_upgraded(self):
        vu = ValidationUpgraded(
            column_name="col",
            rule_type="expect_column_to_exist",
            kwargs={"column": "col"},
            generated_from="baseline",
        )
        assert vu.generated_from == "baseline"

    def test_validation_severity_preserved(self):
        vsp = ValidationSeverityPreserved(
            column_name="col",
            rule_type="expect_column_to_exist",
            kwargs={"column": "col"},
            generated_from="baseline",
            user_severity="warning",
            canonical_severity="critical",
        )
        assert vsp.user_severity == "warning"
        assert vsp.canonical_severity == "critical"


# ============================================================================
# METADATA_COLUMN_DEFINITIONS tests
# ============================================================================


class TestMetadataColumnDefinitions:
    """Test the metadata column definitions constant."""

    def test_all_required_metadata_columns_present(self):
        expected = {
            "meta_source_name",
            "meta_source_checksum",
            "meta_load_dt",
            "meta_snapshot_dt",
            "meta_source_offset",
            "meta_checksum",
            "meta_pipeline_version",
            "meta_component",
        }
        assert set(METADATA_COLUMN_DEFINITIONS.keys()) == expected

    def test_each_definition_has_required_fields(self):
        expected_types = {
            name: definition["data_type"]
            for name, definition in PROVENANCE_COLUMNS.items()
        }
        for name, defn in METADATA_COLUMN_DEFINITIONS.items():
            assert defn["name"] == name
            assert "data_type" in defn
            assert defn["data_type"] == expected_types[name]
            assert defn["source"] == "metadata"
            assert "description" in defn
            assert "nullable" in defn
            # Default constant uses MD/ME/MP for backward compat
            for ctx in ("MD", "ME", "MP"):
                assert defn["nullable"][ctx] is False

    def test_get_metadata_column_definitions_with_context_keys(self):
        """Derives context keys from column nullable dicts."""
        columns = [
            {"name": "col1", "nullable": {"retail": True, "wholesale": False}},
            {"name": "col2", "nullable": {"retail": False, "wholesale": False}},
        ]
        defs = get_metadata_column_definitions(columns)
        for defn in defs.values():
            assert defn["nullable"] == {"retail": False, "wholesale": False}

    def test_get_metadata_column_definitions_simple_boolean(self):
        """Falls back to simple boolean when no per-context dicts exist."""
        columns = [
            {"name": "col1", "nullable": True},
            {"name": "col2", "nullable": False},
        ]
        defs = get_metadata_column_definitions(columns)
        for defn in defs.values():
            assert defn["nullable"] is False

    def test_get_metadata_column_definitions_no_columns(self):
        """Falls back to simple boolean when no columns provided."""
        defs = get_metadata_column_definitions()
        for defn in defs.values():
            assert defn["nullable"] is False


class TestBaselineSyncerSplitRoundTrip:
    """Regression coverage for split UMF sync/load behavior."""

    @pytest.fixture
    def loader(self) -> UMFLoader:
        return UMFLoader()

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
        ):
            return BaselineSyncer()

    def _write_split_spec(self, tmp_path: Path, loader: UMFLoader) -> UMF:
        columns = [
            UMFColumn(name="business_col", data_type="VARCHAR", length=32),
        ]
        for definition in PROVENANCE_COLUMNS.values():
            columns.append(
                UMFColumn(
                    name=definition["name"],
                    data_type=definition["data_type"],
                )
            )

        umf = UMF(
            version="1.0",
            table_name="test_table",
            description="Test table",
            columns=columns,
        )
        loader.save(umf, tmp_path, UMFFormat.SPLIT)
        return umf

    def test_validation_sync_round_trips_split_spec_loadably(
        self, tmp_path: Path, loader: UMFLoader, syncer
    ) -> None:
        self._write_split_spec(tmp_path, loader)

        result = syncer.sync_table(tmp_path)

        assert result.columns_updated == len(PROVENANCE_COLUMNS)

        loaded = loader.load(tmp_path)
        meta_columns = {
            col.name: col for col in loaded.columns if col.name.startswith("meta_")
        }

        assert set(meta_columns) == set(PROVENANCE_COLUMNS)
        for name, definition in PROVENANCE_COLUMNS.items():
            assert meta_columns[name].data_type == definition["data_type"]

    def test_validation_sync_fails_closed_when_write_breaks_loadability(
        self, tmp_path: Path, loader: UMFLoader, syncer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._write_split_spec(tmp_path, loader)

        original_save = syncer._save_column_file
        corrupted = False

        def bad_save(column_file: Path, data: dict) -> None:
            nonlocal corrupted
            if not corrupted and column_file.name == "meta_source_name.yaml":
                corrupted = True
                bad_data = deepcopy(data)
                bad_data["column"]["data_type"] = "StringType"
                original_save(column_file, bad_data)
                return
            original_save(column_file, data)

        monkeypatch.setattr(syncer, "_save_column_file", bad_save)

        with pytest.raises(ValueError, match="Validation failed after writing"):
            syncer.sync_table(tmp_path)


# ============================================================================
# BaselineSyncer core logic tests (mocked dependencies)
# ============================================================================


class TestBaselineSyncerInit:
    """Test BaselineSyncer initialization."""

    def test_init_requires_ruamel(self):
        """Should raise ImportError if ruamel.yaml is not available."""
        with patch("tablespec.sync_baseline._ruamel_available", False):
            with pytest.raises(ImportError, match="ruamel.yaml"):
                BaselineSyncer()

    def test_init_requires_umf_loader(self):
        """Should raise ImportError if UMFLoader is not available."""
        with patch("tablespec.sync_baseline._umf_loader_available", False):
            with pytest.raises(ImportError, match="UMFLoader"):
                BaselineSyncer()


class TestBaselineSyncerNormalizeExpectation:
    """Test _normalize_expectation method."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_normalize_simple(self, syncer):
        exp = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "critical"},
        }
        result = syncer._normalize_expectation(exp)
        assert result == ("expect_column_to_exist", (("column", "col1"),))

    def test_normalize_ignores_meta(self, syncer):
        """Two expectations that differ only in meta should normalize the same."""
        exp1 = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "critical"},
        }
        exp2 = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "warning", "extra": "data"},
        }
        assert syncer._normalize_expectation(exp1) == syncer._normalize_expectation(
            exp2
        )

    def test_normalize_handles_list_kwargs(self, syncer):
        exp = {
            "type": "expect_column_values_to_be_in_set",
            "kwargs": {"column": "col1", "value_set": ["A", "B"]},
        }
        result = syncer._normalize_expectation(exp)
        # Lists should become tuples
        assert result[0] == "expect_column_values_to_be_in_set"
        kwargs_dict = dict(result[1])
        assert kwargs_dict["value_set"] == ("A", "B")

    def test_normalize_handles_dict_kwargs(self, syncer):
        exp = {
            "type": "test_type",
            "kwargs": {"nested": {"a": 1, "b": 2}},
        }
        result = syncer._normalize_expectation(exp)
        # Dicts should become sorted tuples of tuples
        kwargs_dict = dict(result[1])
        assert kwargs_dict["nested"] == (("a", 1), ("b", 2))


class TestBaselineSyncerCompareExpectations:
    """Test _compare_expectations method."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_exact_match(self, syncer):
        canonical = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "critical"},
        }
        existing = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "critical"},
        }
        assert syncer._compare_expectations(canonical, existing) == "match"

    def test_severity_only_difference(self, syncer):
        canonical = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "critical"},
        }
        existing = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "warning"},
        }
        assert syncer._compare_expectations(canonical, existing) == "severity_only"

    def test_kwargs_value_conflict(self, syncer):
        canonical = {
            "type": "expect_column_value_lengths_to_be_between",
            "kwargs": {"column": "col1", "max_value": 100},
            "meta": {"severity": "warning"},
        }
        existing = {
            "type": "expect_column_value_lengths_to_be_between",
            "kwargs": {"column": "col1", "max_value": 200},
            "meta": {"severity": "warning"},
        }
        result = syncer._compare_expectations(canonical, existing)
        assert "max_value" in result
        assert "100" in result
        assert "200" in result

    def test_different_kwargs_keys(self, syncer):
        canonical = {
            "type": "test_type",
            "kwargs": {"column": "col1", "extra": True},
            "meta": {},
        }
        existing = {
            "type": "test_type",
            "kwargs": {"column": "col1"},
            "meta": {},
        }
        result = syncer._compare_expectations(canonical, existing)
        assert "Different kwargs keys" in result


class TestBaselineSyncerFindStructuralMatch:
    """Test _find_structural_match method."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_finds_matching_unmarked(self, syncer):
        canonical = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"generated_from": "baseline"},
        }
        unmarked = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {},
            },
        ]
        result = syncer._find_structural_match(canonical, unmarked)
        assert result is not None
        assert result["type"] == "expect_column_to_exist"

    def test_no_match_returns_none(self, syncer):
        canonical = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
        }
        unmarked = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col2"},
            },
        ]
        result = syncer._find_structural_match(canonical, unmarked)
        assert result is None


class TestBaselineSyncerColumnsMatch:
    """Test _columns_match method."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_matching_columns(self, syncer):
        canonical = {
            "name": "meta_load_dt",
            "data_type": "TimestampType",
            "source": "metadata",
            "description": "Timestamp when ingestion ran (Unix epoch)",
            "nullable": {"MD": False},
        }
        existing = {
            "name": "meta_load_dt",
            "data_type": "TimestampType",
            "source": "metadata",
            "description": "Timestamp when ingestion ran (Unix epoch)",
            "nullable": {"MD": False},
            "user_notes": "custom note",
        }
        assert syncer._columns_match(canonical, existing) is True

    def test_non_matching_columns(self, syncer):
        canonical = {
            "name": "meta_load_dt",
            "data_type": "TimestampType",
            "source": "metadata",
            "description": "Timestamp when ingestion ran (Unix epoch)",
            "nullable": {"MD": False},
        }
        existing = {
            "name": "meta_load_dt",
            "data_type": "StringType",  # Different
            "source": "metadata",
            "description": "old description",
            "nullable": {"MD": False},
        }
        assert syncer._columns_match(canonical, existing) is False


class TestBaselineSyncerSyncColumnValidations:
    """Test _sync_column_validations core logic."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_adds_new_canonical(self, syncer):
        """New canonical expectations should be added."""
        canonical = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"generated_from": "baseline"},
            },
        ]
        existing: list[dict] = []

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=False
        )

        assert stats["added"] == 1
        assert len(updated) == 1
        assert updated[0]["type"] == "expect_column_to_exist"

    def test_exact_match_no_changes(self, syncer):
        """Exact match should keep existing, no adds/conflicts."""
        exp = {
            "type": "expect_column_to_exist",
            "kwargs": {"column": "col1"},
            "meta": {"severity": "critical", "generated_from": "baseline"},
        }
        canonical = [exp.copy()]
        existing = [exp.copy()]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=False
        )

        assert stats["added"] == 0
        assert stats["conflicts"] == 0
        assert stats["severity_preserved"] == 0
        assert len(updated) == 1

    def test_severity_only_preserved(self, syncer):
        """User severity customization should be preserved."""
        canonical = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"severity": "critical", "generated_from": "baseline"},
            },
        ]
        existing = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"severity": "warning", "generated_from": "baseline"},
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=False
        )

        assert stats["severity_preserved"] == 1
        assert len(stats["severity_preserved_details"]) == 1
        # Should keep existing (with user's severity)
        assert updated[0]["meta"]["severity"] == "warning"

    def test_different_kwargs_treated_as_new_and_outdated(self, syncer):
        """Different kwargs means different normalization keys - old is outdated, new is added."""
        canonical = [
            {
                "type": "expect_column_value_lengths_to_be_between",
                "kwargs": {"column": "col1", "max_value": 100},
                "meta": {"severity": "warning", "generated_from": "baseline"},
            },
        ]
        existing = [
            {
                "type": "expect_column_value_lengths_to_be_between",
                "kwargs": {"column": "col1", "max_value": 200},
                "meta": {"severity": "warning", "generated_from": "baseline"},
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=False
        )

        # Different kwargs = different keys, so canonical is added as new
        assert stats["added"] == 1
        # Old programmatic is kept in safe mode (not cleaned)
        assert len(updated) == 2

    def test_aggressive_upgrade(self, syncer):
        """Aggressive mode should upgrade unmarked matching validations."""
        canonical = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"severity": "critical", "generated_from": "baseline"},
            },
        ]
        existing = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {},  # No generated_from marker
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=True, clean_outdated=False
        )

        assert stats["upgraded"] == 1
        assert len(stats["upgraded_details"]) == 1
        # Updated should have the canonical version (with generated_from)
        assert updated[0]["meta"]["generated_from"] == "baseline"

    def test_aggressive_no_match_adds_new(self, syncer):
        """Aggressive mode without structural match should still add new."""
        canonical = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"generated_from": "baseline"},
            },
        ]
        existing = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "col1"},
                "meta": {},
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=True, clean_outdated=False
        )

        assert stats["added"] == 1
        assert stats["upgraded"] == 0

    def test_clean_outdated_removes_old_programmatic(self, syncer):
        """Clean mode should remove outdated programmatic validations."""
        canonical: list[dict] = []  # No canonical expectations
        existing = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"generated_from": "baseline"},
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=True
        )

        assert stats["removed"] == 1
        assert len(stats["removed_details"]) == 1
        # Outdated programmatic should not be in updated
        assert len(updated) == 0

    def test_safe_mode_keeps_old_programmatic(self, syncer):
        """Safe mode (clean_outdated=False) should keep old programmatic validations."""
        canonical: list[dict] = []
        existing = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"generated_from": "baseline"},
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=False
        )

        assert stats.get("removed", 0) == 0
        # Old programmatic should still be present
        assert len(updated) == 1

    def test_user_validations_preserved(self, syncer):
        """User validations should always be preserved."""
        canonical = [
            {
                "type": "expect_column_to_exist",
                "kwargs": {"column": "col1"},
                "meta": {"generated_from": "baseline"},
            },
        ]
        existing = [
            {
                "type": "expect_column_values_to_match_regex",
                "kwargs": {"column": "col1", "regex": "^[A-Z]+$"},
                "meta": {"generated_from": "user_input"},
            },
        ]

        updated, stats = syncer._sync_column_validations(
            "col1", canonical, existing, aggressive=False, clean_outdated=False
        )

        # Should have canonical + user validation
        assert len(updated) == 2
        types = [v["type"] for v in updated]
        assert "expect_column_to_exist" in types
        assert "expect_column_values_to_match_regex" in types


class TestBaselineSyncerSortRecursive:
    """Test _sort_recursive method."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_sorts_dict_keys(self, syncer):
        data = {"z": 1, "a": 2, "m": 3}
        result = syncer._sort_recursive(data)
        assert list(result.keys()) == ["a", "m", "z"]

    def test_preserves_list_order(self, syncer):
        data = [3, 1, 2]
        result = syncer._sort_recursive(data)
        assert result == [3, 1, 2]

    def test_filters_none_values(self, syncer):
        data = {"a": 1, "b": None, "c": 3}
        result = syncer._sort_recursive(data)
        assert "b" not in result
        assert result == {"a": 1, "c": 3}

    def test_recursive_nested(self, syncer):
        data = {"z": {"b": 2, "a": 1}, "a": [{"y": 1, "x": 2}]}
        result = syncer._sort_recursive(data)
        assert list(result.keys()) == ["a", "z"]
        assert list(result["z"].keys()) == ["a", "b"]
        assert list(result["a"][0].keys()) == ["x", "y"]

    def test_passthrough_primitives(self, syncer):
        assert syncer._sort_recursive(42) == 42
        assert syncer._sort_recursive("hello") == "hello"
        assert syncer._sort_recursive(True) is True


class TestBaselineSyncerStripTrailingWhitespace:
    """Test _strip_trailing_whitespace method."""

    @pytest.fixture
    def syncer(self):
        with (
            patch("tablespec.sync_baseline._ruamel_available", True),
            patch("tablespec.sync_baseline._umf_loader_available", True),
            patch("tablespec.sync_baseline.UMFLoader"),
            patch("tablespec.sync_baseline.YAML"),
        ):
            return BaselineSyncer()

    def test_strips_string(self, syncer):
        assert syncer._strip_trailing_whitespace("hello   ") == "hello"

    def test_strips_in_dict(self, syncer):
        result = syncer._strip_trailing_whitespace({"key": "value  "})
        assert result == {"key": "value"}

    def test_strips_in_list(self, syncer):
        result = syncer._strip_trailing_whitespace(["a  ", "b  "])
        assert result == ["a", "b"]

    def test_passes_through_non_string(self, syncer):
        assert syncer._strip_trailing_whitespace(42) == 42
        assert syncer._strip_trailing_whitespace(None) is None

    def test_recursive(self, syncer):
        data = {"a": {"b": "hello  "}, "c": ["world  "]}
        result = syncer._strip_trailing_whitespace(data)
        assert result == {"a": {"b": "hello"}, "c": ["world"]}
