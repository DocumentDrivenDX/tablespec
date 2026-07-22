"""Tests for survivorship display formatting and validation."""

import json

import pytest

from tablespec.survivorship_display import (
    SurvivorshipValidator,
    format_survivorship,
    load_survivorship,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_surv_data():
    """Minimal valid survivorship data."""
    return {
        "mappings": {
            "member_id": {
                "survivorship": {
                    "strategy": "priority",
                    "explanation": "Use highest priority source.",
                },
                "candidates": [
                    {"table": "claims", "column": "member_id", "priority": 1},
                ],
            }
        }
    }


@pytest.fixture
def full_surv_data():
    """Full survivorship data with metadata, strategies, normalization."""
    return {
        "metadata": {
            "table_name": "golden_member",
            "description": "Survivorship rules for golden member table.",
        },
        "survivorship_strategies": {
            "priority": {"description": "Pick candidate with highest priority"},
            "latest": {"description": "Pick candidate with latest timestamp"},
        },
        "mappings": {
            "member_id": {
                "survivorship": {
                    "strategy": "priority",
                    "explanation": "Use highest priority source.",
                    "description": "Primary member identifier.",
                },
                "candidates": [
                    {"table": "claims", "column": "member_id", "priority": 1},
                    {"table": "enrollment", "column": "member_id", "priority": 2},
                ],
            },
            "first_name": {
                "survivorship": {
                    "strategy": "latest",
                    "explanation": "Use latest record.",
                    "description": "Member first name.",
                },
                "candidates": [],
            },
        },
        "normalization": {
            "uppercase": {
                "description": "Convert to uppercase",
                "example": "john -> JOHN",
            }
        },
    }


# ---------------------------------------------------------------------------
# Tests: load_survivorship
# ---------------------------------------------------------------------------


class TestLoadSurvivorship:
    """Test loading survivorship data from files."""

    def test_load_from_json_file(self, tmp_path):
        """Load survivorship from a compiled JSON file."""
        data = {"derivations": {"mappings": {"col_a": {}}}}
        json_file = tmp_path / "table.json"
        json_file.write_text(json.dumps(data))

        result = load_survivorship(json_file)
        assert result == {"mappings": {"col_a": {}}}

    def test_load_json_no_derivations(self, tmp_path):
        """JSON file without derivations returns None."""
        json_file = tmp_path / "table.json"
        json_file.write_text(json.dumps({"version": "1.0"}))

        result = load_survivorship(json_file)
        assert result is None

    def test_load_non_json_file(self, tmp_path):
        """Non-JSON file returns None."""
        yaml_file = tmp_path / "table.yaml"
        yaml_file.write_text("version: 1.0")

        result = load_survivorship(yaml_file)
        assert result is None

    def test_load_nonexistent_path(self, tmp_path):
        """Non-existent path returns None."""
        result = load_survivorship(tmp_path / "nonexistent")
        assert result is None

    def test_load_from_directory_no_loader(self, tmp_path):
        """Directory loading delegates to UMFLoader; returns None on failure."""
        table_dir = tmp_path / "my_table"
        table_dir.mkdir()
        # No valid UMF files, so it should return None gracefully
        result = load_survivorship(table_dir)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: SurvivorshipValidator
# ---------------------------------------------------------------------------


class TestSurvivorshipValidator:
    """Test survivorship rule validation."""

    def test_valid_minimal(self, minimal_surv_data):
        """Minimal valid data passes validation."""
        valid, errors = SurvivorshipValidator.validate(minimal_surv_data)
        assert valid
        assert errors == []

    def test_not_a_dict(self):
        """Non-dict root fails."""
        valid, errors = SurvivorshipValidator.validate("not a dict")
        assert not valid
        assert "not a dict" in errors[0]

    def test_missing_mappings(self):
        """Missing mappings section fails."""
        valid, errors = SurvivorshipValidator.validate({"metadata": {}})
        assert not valid
        assert any("mappings" in e for e in errors)

    def test_mappings_not_dict(self):
        """mappings must be a dict."""
        valid, errors = SurvivorshipValidator.validate({"mappings": "nope"})
        assert not valid
        assert any("mappings must be a dict" in e for e in errors)

    def test_mapping_not_dict(self):
        """Individual mapping entry must be a dict."""
        data = {"mappings": {"col_a": "not a dict"}}
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("col_a" in e and "not a dict" in e for e in errors)

    def test_missing_survivorship_key(self):
        """Mapping without survivorship key fails."""
        data = {"mappings": {"col_a": {"candidates": []}}}
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("missing 'survivorship'" in e for e in errors)

    def test_survivorship_not_dict(self):
        """survivorship must be a dict."""
        data = {"mappings": {"col_a": {"survivorship": "just_a_string"}}}
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("survivorship is not a dict" in e for e in errors)

    def test_missing_strategy(self):
        """Missing strategy field."""
        data = {"mappings": {"col_a": {"survivorship": {"explanation": "x"}}}}
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("missing 'strategy'" in e for e in errors)

    def test_missing_explanation(self):
        """Missing explanation field."""
        data = {"mappings": {"col_a": {"survivorship": {"strategy": "priority"}}}}
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("missing 'explanation'" in e for e in errors)

    def test_undefined_strategy(self):
        """Strategy not defined in survivorship_strategies."""
        data = {
            "survivorship_strategies": {"priority": {}},
            "mappings": {
                "col_a": {
                    "survivorship": {
                        "strategy": "unknown_strat",
                        "explanation": "x",
                    },
                    "candidates": [],
                }
            },
        }
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("not defined" in e for e in errors)

    def test_candidates_not_list(self):
        """candidates must be a list."""
        data = {
            "mappings": {
                "col_a": {
                    "survivorship": {"strategy": "priority", "explanation": "x"},
                    "candidates": "not_a_list",
                }
            }
        }
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("candidates must be a list" in e for e in errors)

    def test_candidate_not_dict(self):
        """Each candidate must be a dict."""
        data = {
            "mappings": {
                "col_a": {
                    "survivorship": {"strategy": "priority", "explanation": "x"},
                    "candidates": ["not_a_dict"],
                }
            }
        }
        valid, errors = SurvivorshipValidator.validate(data)
        assert not valid
        assert any("not a dict" in e for e in errors)

    def test_candidate_table_validation(self):
        """Candidate referencing non-existent table is caught."""
        data = {
            "mappings": {
                "col_a": {
                    "survivorship": {"strategy": "priority", "explanation": "x"},
                    "candidates": [
                        {"table": "nonexistent_table", "column": "col_x", "priority": 1}
                    ],
                }
            }
        }
        all_tables = {"claims": ["member_id", "amount"]}
        valid, errors = SurvivorshipValidator.validate(data, all_tables=all_tables)
        assert not valid
        assert any("nonexistent_table" in e and "does not exist" in e for e in errors)

    def test_candidate_column_validation(self):
        """Candidate referencing non-existent column is caught."""
        data = {
            "mappings": {
                "col_a": {
                    "survivorship": {"strategy": "priority", "explanation": "x"},
                    "candidates": [
                        {"table": "claims", "column": "bad_col", "priority": 1}
                    ],
                }
            }
        }
        all_tables = {"claims": ["member_id", "amount"]}
        valid, errors = SurvivorshipValidator.validate(data, all_tables=all_tables)
        assert not valid
        assert any("bad_col" in e and "not found" in e for e in errors)

    def test_valid_with_all_tables(self):
        """Valid mapping against all_tables passes."""
        data = {
            "mappings": {
                "col_a": {
                    "survivorship": {"strategy": "priority", "explanation": "x"},
                    "candidates": [
                        {"table": "claims", "column": "member_id", "priority": 1}
                    ],
                }
            }
        }
        all_tables = {"claims": ["member_id", "amount"]}
        valid, errors = SurvivorshipValidator.validate(data, all_tables=all_tables)
        assert valid
        assert errors == []


# ---------------------------------------------------------------------------
# Tests: format_survivorship
# ---------------------------------------------------------------------------


class TestFormatSurvivorship:
    """Test survivorship display formatting."""

    def test_format_minimal(self, minimal_surv_data):
        """Minimal data formats without error."""
        output = format_survivorship(minimal_surv_data)
        assert "member_id" in output
        assert "Strategy: priority" in output
        assert "Summary" in output
        assert "Total columns: 1" in output

    def test_format_with_metadata(self, full_surv_data):
        """Metadata section is included."""
        output = format_survivorship(full_surv_data)
        assert "Metadata" in output
        assert "golden_member" in output

    def test_format_verbose_strategies(self, full_surv_data):
        """Verbose mode shows survivorship strategies."""
        output = format_survivorship(full_surv_data, verbose=True)
        assert "Survivorship Strategies" in output
        assert "priority" in output
        assert "latest" in output

    def test_format_verbose_normalization(self, full_surv_data):
        """Verbose mode shows normalization rules."""
        output = format_survivorship(full_surv_data, verbose=True)
        assert "Normalization Rules" in output
        assert "uppercase" in output
        assert "JOHN" in output

    def test_format_no_strategies_in_non_verbose(self, full_surv_data):
        """Non-verbose mode hides strategy details."""
        output = format_survivorship(full_surv_data, verbose=False)
        assert "Survivorship Strategies" not in output

    def test_format_candidates_with_priority(self, full_surv_data):
        """Candidates are sorted by priority."""
        output = format_survivorship(full_surv_data)
        lines = output.split("\n")
        source_lines = [line for line in lines if "[1]" in line or "[2]" in line]
        assert len(source_lines) == 2

    def test_format_no_candidates(self, full_surv_data):
        """Columns with no candidates show appropriate message."""
        output = format_survivorship(full_surv_data)
        assert "None (no direct mapping)" in output

    def test_format_summary_stats(self, full_surv_data):
        """Summary section has correct counts."""
        output = format_survivorship(full_surv_data)
        assert "Total columns: 2" in output
        assert "With source mappings: 1" in output
        assert "Without source mappings: 1" in output
        assert "Strategies defined: 2" in output

    def test_format_empty_mappings(self):
        """Empty mappings still produces summary."""
        data = {"mappings": {}}
        output = format_survivorship(data)
        assert "Total columns: 0" in output
