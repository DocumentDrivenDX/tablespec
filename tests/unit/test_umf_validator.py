"""Unit tests for UMFValidator: file validation, business rules, defaults, duplicate fixing."""

import json

import pytest
import yaml

from tablespec.umf_validator import UMFValidationError, UMFValidator

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


@pytest.fixture()
def validator():
    """Create a UMFValidator with the default schema."""
    return UMFValidator()


@pytest.fixture()
def valid_umf_data():
    """Minimal valid UMF data dict."""
    return {
        "version": "1.0",
        "table_name": "test_table",
        "columns": [
            {"name": "col1", "data_type": "VARCHAR"},
        ],
    }


@pytest.fixture()
def valid_umf_file(tmp_path, valid_umf_data):
    """Write minimal valid UMF to a temp YAML file."""
    file_path = tmp_path / "test.umf.yaml"
    file_path.write_text(yaml.dump(valid_umf_data), encoding="utf-8")
    return file_path


class TestUMFValidatorInit:
    def test_default_schema_loads(self):
        v = UMFValidator()
        assert v.schema is not None
        assert "properties" in v.schema

    def test_missing_schema_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            UMFValidator(schema_path=tmp_path / "nonexistent.json")

    def test_custom_schema(self, tmp_path):
        schema = {"type": "object", "properties": {}}
        schema_path = tmp_path / "custom.schema.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        v = UMFValidator(schema_path=schema_path)
        assert v.schema == schema


class TestValidateFile:
    def test_valid_file(self, validator, valid_umf_file):
        assert validator.validate_file(valid_umf_file) is True

    def test_file_not_found(self, validator, tmp_path):
        with pytest.raises(FileNotFoundError):
            validator.validate_file(tmp_path / "missing.yaml")

    def test_invalid_yaml(self, validator, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml::", encoding="utf-8")
        with pytest.raises(UMFValidationError, match="Invalid YAML"):
            validator.validate_file(bad_file)

    def test_invalid_yaml_no_raise(self, validator, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml::", encoding="utf-8")
        assert validator.validate_file(bad_file, raise_on_error=False) is False

    def test_schema_invalid_file(self, validator, tmp_path):
        invalid_data = {"version": "1.0"}  # missing table_name and columns
        file_path = tmp_path / "invalid.umf.yaml"
        file_path.write_text(yaml.dump(invalid_data), encoding="utf-8")
        with pytest.raises(UMFValidationError):
            validator.validate_file(file_path)

    def test_schema_invalid_no_raise(self, validator, tmp_path):
        invalid_data = {"version": "1.0"}
        file_path = tmp_path / "invalid.umf.yaml"
        file_path.write_text(yaml.dump(invalid_data), encoding="utf-8")
        assert validator.validate_file(file_path, raise_on_error=False) is False


class TestValidateData:
    def test_valid_data(self, validator, valid_umf_data):
        assert validator.validate_data(valid_umf_data) is True

    def test_missing_required_fields(self, validator):
        with pytest.raises(UMFValidationError):
            validator.validate_data({"version": "1.0"})

    def test_missing_required_no_raise(self, validator):
        assert (
            validator.validate_data({"version": "1.0"}, raise_on_error=False) is False
        )

    def test_invalid_version_format(self, validator):
        data = {
            "version": "abc",
            "table_name": "test_table",
            "columns": [{"name": "col1", "data_type": "VARCHAR"}],
        }
        with pytest.raises(UMFValidationError):
            validator.validate_data(data)


class TestValidateDirectory:
    def test_valid_directory(self, validator, tmp_path, valid_umf_data):
        for i in range(3):
            f = tmp_path / f"table{i}.umf.yaml"
            f.write_text(yaml.dump(valid_umf_data), encoding="utf-8")
        results = validator.validate_directory(tmp_path)
        assert len(results) == 3
        assert all(results.values())

    def test_missing_directory(self, validator, tmp_path):
        with pytest.raises(ValueError, match="Directory not found"):
            validator.validate_directory(tmp_path / "nonexistent")

    def test_no_matching_files(self, validator, tmp_path):
        results = validator.validate_directory(tmp_path)
        assert results == {}

    def test_mixed_valid_invalid(self, validator, tmp_path, valid_umf_data):
        good = tmp_path / "good.umf.yaml"
        good.write_text(yaml.dump(valid_umf_data), encoding="utf-8")
        bad = tmp_path / "bad.umf.yaml"
        bad.write_text(yaml.dump({"version": "1.0"}), encoding="utf-8")
        results = validator.validate_directory(tmp_path, raise_on_error=False)
        assert len(results) == 2
        assert results[str(good)] is True
        assert results[str(bad)] is False

    def test_raise_on_error_with_invalid(self, validator, tmp_path):
        bad = tmp_path / "bad.umf.yaml"
        bad.write_text(yaml.dump({"version": "1.0"}), encoding="utf-8")
        with pytest.raises(UMFValidationError):
            validator.validate_directory(tmp_path, raise_on_error=True)

    def test_custom_pattern(self, validator, tmp_path, valid_umf_data):
        f = tmp_path / "data.yml"
        f.write_text(yaml.dump(valid_umf_data), encoding="utf-8")
        results = validator.validate_directory(tmp_path, pattern="*.yml")
        assert len(results) == 1


class TestBusinessRules:
    def test_duplicate_column_names_raises(self, validator):
        data = {
            "version": "1.0",
            "table_name": "test_table",
            "columns": [
                {"name": "col1", "data_type": "VARCHAR"},
                {"name": "col1", "data_type": "INTEGER"},
            ],
        }
        with pytest.raises(UMFValidationError, match="Column names must be unique"):
            validator.validate_data(data)

    def test_invalid_version_format_business_rule(self, validator):
        data = {
            "version": "1.0abc",
            "table_name": "test_table",
            "columns": [{"name": "col1", "data_type": "VARCHAR"}],
        }
        # The JSON schema pattern check may catch this first, but business rules also check
        with pytest.raises(UMFValidationError):
            validator.validate_data(data)


class TestApplyDefaultSpecifications:
    def test_varchar_gets_default_length(self, validator):
        data = {
            "columns": [
                {"name": "col1", "data_type": "VARCHAR"},
            ],
        }
        result = validator.apply_default_specifications(data)
        assert result["columns"][0]["length"] == 255

    def test_varchar_keeps_existing_length(self, validator):
        data = {
            "columns": [
                {"name": "col1", "data_type": "VARCHAR", "length": 50},
            ],
        }
        result = validator.apply_default_specifications(data)
        assert result["columns"][0]["length"] == 50

    def test_decimal_gets_default_precision_and_scale(self, validator):
        data = {
            "columns": [
                {"name": "col1", "data_type": "DECIMAL"},
            ],
        }
        result = validator.apply_default_specifications(data)
        assert result["columns"][0]["precision"] == 18
        assert result["columns"][0]["scale"] == 2

    def test_decimal_keeps_existing_precision(self, validator):
        data = {
            "columns": [
                {"name": "col1", "data_type": "DECIMAL", "precision": 10, "scale": 4},
            ],
        }
        result = validator.apply_default_specifications(data)
        assert result["columns"][0]["precision"] == 10
        assert result["columns"][0]["scale"] == 4

    def test_no_columns_key(self, validator):
        data = {}
        result = validator.apply_default_specifications(data)
        assert result == {}

    def test_non_varchar_not_affected(self, validator):
        data = {
            "columns": [
                {"name": "col1", "data_type": "INTEGER"},
            ],
        }
        result = validator.apply_default_specifications(data)
        assert "length" not in result["columns"][0]


class TestFixDuplicateColumnNames:
    def test_no_duplicates(self, validator):
        data = {
            "columns": [
                {"name": "col1"},
                {"name": "col2"},
            ],
        }
        result = validator.fix_duplicate_column_names(data)
        assert result["columns"][0]["name"] == "col1"
        assert result["columns"][1]["name"] == "col2"

    def test_duplicates_get_suffix(self, validator):
        data = {
            "columns": [
                {"name": "col1"},
                {"name": "col1"},
                {"name": "col1"},
            ],
        }
        result = validator.fix_duplicate_column_names(data)
        names = [c["name"] for c in result["columns"]]
        assert names == ["col1", "col1_2", "col1_3"]

    def test_duplicate_stores_original_name(self, validator):
        data = {
            "columns": [
                {"name": "col1"},
                {"name": "col1"},
            ],
        }
        result = validator.fix_duplicate_column_names(data)
        assert result["columns"][1]["original_name"] == "col1"

    def test_does_not_overwrite_existing_original_name(self, validator):
        data = {
            "columns": [
                {"name": "col1"},
                {"name": "col1", "original_name": "kept"},
            ],
        }
        result = validator.fix_duplicate_column_names(data)
        assert result["columns"][1]["original_name"] == "kept"

    def test_no_columns_key(self, validator):
        data = {}
        result = validator.fix_duplicate_column_names(data)
        assert result == {}


class TestGetValidationErrors:
    def test_valid_returns_empty(self, validator, valid_umf_data):
        errors = validator.get_validation_errors(valid_umf_data)
        assert errors == []

    def test_schema_errors_returned(self, validator):
        errors = validator.get_validation_errors({"version": "1.0"})
        assert len(errors) > 0
        assert any("Schema error" in e for e in errors)

    def test_business_rule_errors_returned(self, validator):
        data = {
            "version": "1.0",
            "table_name": "test_table",
            "columns": [
                {"name": "col1", "data_type": "VARCHAR"},
                {"name": "col1", "data_type": "VARCHAR"},
            ],
        }
        errors = validator.get_validation_errors(data)
        assert any("Business rule error" in e for e in errors)


class TestUMFValidationError:
    def test_error_with_message(self):
        err = UMFValidationError("test error")
        assert str(err) == "test error"
        assert err.errors == []

    def test_error_with_errors_list(self):
        err = UMFValidationError("test", errors=["e1", "e2"])
        assert err.errors == ["e1", "e2"]
