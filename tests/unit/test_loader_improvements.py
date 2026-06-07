# @covers US-034-AC1
"""Tests for UMF loader targeted error messages, expectation type validation, and roundtrip."""

import pytest

from tablespec.umf_loader import UMFLoader
from tablespec.umf_validator import UMFValidator

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestTargetedErrorMessages:
    def test_missing_table_yaml(self, tmp_path):
        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "col1.yaml").write_text(
            "column:\n  name: id\n  data_type: INTEGER\n"
        )
        with pytest.raises(FileNotFoundError, match="no table.yaml"):
            UMFLoader().load(tmp_path)

    def test_missing_columns_dir(self, tmp_path):
        (tmp_path / "table.yaml").write_text("version: '1.0'\ntable_name: test\n")
        with pytest.raises(FileNotFoundError, match="no columns"):
            UMFLoader().load(tmp_path)


class TestExpectationTypeValidation:
    def test_unknown_type_flagged(self):
        validator = UMFValidator()
        umf_data = {
            "version": "1.0",
            "table_name": "t",
            "columns": [{"name": "id", "data_type": "INTEGER"}],
            "validation_rules": {
                "expectations": [
                    {"type": "expect_column_values_to_fly", "kwargs": {"column": "id"}}
                ]
            },
        }
        errors = validator.get_validation_errors(umf_data)
        assert any("Unknown expectation type" in e for e in errors)

    def test_known_type_passes(self):
        validator = UMFValidator()
        umf_data = {
            "version": "1.0",
            "table_name": "t",
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
        errors = validator.get_validation_errors(umf_data)
        assert not any("Unknown expectation type" in e for e in errors)

    def test_unknown_type_in_quality_checks(self):
        validator = UMFValidator()
        umf_data = {
            "version": "1.0",
            "table_name": "t",
            "columns": [{"name": "id", "data_type": "INTEGER"}],
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {"type": "expect_magic"},
                        "severity": "warning",
                        "blocking": False,
                    }
                ]
            },
        }
        errors = validator.get_validation_errors(umf_data)
        assert any("Unknown expectation type" in e for e in errors)
