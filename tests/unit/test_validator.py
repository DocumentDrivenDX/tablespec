"""Unit tests for validator module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tablespec.models import (
    ForeignKey,
    Relationships,
    UMF,
    UMFColumn,
    ValidationRules,
)
from tablespec.validator import (
    ValidationContext,
    _format_change_details,
    _get_rule_identifier,
    _get_saved_files,
    _group_changes_by_note,
    convert_table,
    show_table_info,
    validate_pipeline,
    validate_table,
)

pytestmark = pytest.mark.no_spark


def _make_umf(
    table_name: str = "test_table",
    columns: list[str] | None = None,
    validation_rules: ValidationRules | None = None,
    relationships: Relationships | None = None,
    aliases: list[str] | None = None,
    derivations: dict | None = None,
    version: str = "1.0",
) -> UMF:
    """Helper to create a minimal UMF."""
    if columns is None:
        columns = ["id", "name"]
    cols = [UMFColumn(name=c, data_type="VARCHAR") for c in columns]
    return UMF(
        table_name=table_name,
        version=version,
        columns=cols,
        validation_rules=validation_rules,
        relationships=relationships,
        aliases=aliases,
        derivations=derivations,
    )


# ---------------------------------------------------------------------------
# ValidationContext
# ---------------------------------------------------------------------------


class TestValidationContext:
    """Tests for ValidationContext caching and loading."""

    def test_clear_cache(self):
        """clear_cache should empty the cache."""
        ctx = ValidationContext()
        # Manually add entry
        ctx.umf_cache[Path("/fake")] = (0.0, _make_umf())
        assert len(ctx.umf_cache) == 1
        ctx.clear_cache()
        assert len(ctx.umf_cache) == 0

    def test_load_umf_caches_result(self, tmp_path):
        """load_umf should cache the result and return cached on second call."""
        ctx = ValidationContext()
        umf = _make_umf()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        # Create a file so stat works
        table_file = tmp_path / "table.yaml"
        table_file.write_text("dummy")

        result1 = ctx.load_umf(tmp_path)
        assert result1 is umf
        assert ctx.converter.load.call_count == 1

        # Second call should use cache
        result2 = ctx.load_umf(tmp_path)
        assert result2 is umf
        assert ctx.converter.load.call_count == 1  # not called again

    def test_load_umf_invalidates_on_mtime_change(self, tmp_path):
        """Cache should be invalidated when file mtime changes."""
        ctx = ValidationContext()
        umf1 = _make_umf(table_name="v1")
        umf2 = _make_umf(table_name="v2")
        ctx.converter = MagicMock()
        ctx.converter.load.side_effect = [umf1, umf2]

        table_file = tmp_path / "table.yaml"
        table_file.write_text("v1")

        result1 = ctx.load_umf(tmp_path)
        assert result1.table_name == "v1"

        # Change file content (and mtime)
        import time

        time.sleep(0.05)
        table_file.write_text("v2")

        result2 = ctx.load_umf(tmp_path)
        assert result2.table_name == "v2"
        assert ctx.converter.load.call_count == 2

    def test_load_umf_file_path(self, tmp_path):
        """load_umf should work with a direct file path (not directory)."""
        ctx = ValidationContext()
        umf = _make_umf()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        yaml_file = tmp_path / "my_table.yaml"
        yaml_file.write_text("dummy")

        result = ctx.load_umf(yaml_file)
        assert result is umf


# ---------------------------------------------------------------------------
# validate_table
# ---------------------------------------------------------------------------


class TestValidateTable:
    """Tests for validate_table function."""

    def _make_context(self, umf: UMF) -> ValidationContext:
        """Create a ValidationContext that returns the given UMF."""
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf
        ctx.converter.validate_filename_pattern.return_value = []
        return ctx

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_valid_table_passes(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """A well-formed table should pass validation."""
        umf = _make_umf()
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is True
        assert errors == []

    @patch("tablespec.validator.validate_naming_conventions")
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_naming_errors_reported(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Naming convention errors should be reported."""
        mock_naming.return_value = [("test_table", "Table name must be lowercase")]
        umf = _make_umf()
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("Naming error" in e for e in errors)

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_invalid_pyspark_type_in_expectation(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Expectation with invalid type_ should produce an error."""
        expectations = [
            {
                "type": "expect_column_values_to_be_of_type",
                "kwargs": {"column": "id", "type_": "INVALID_TYPE"},
            }
        ]
        umf = _make_umf(
            validation_rules=ValidationRules(expectations=expectations),
        )
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("Invalid type_" in e for e in errors)

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_missing_expectation_type_field(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Expectation without 'type' field should produce error."""
        expectations = [{"kwargs": {"column": "id"}}]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("Missing 'type' field" in e for e in errors)

    @pytest.mark.filterwarnings(
        "ignore:ValidationRules contains ingested-stage expectations"
    )
    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_pending_implementation_skipped(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Pending implementation expectations should be silently skipped."""
        expectations = [
            {"type": "expect_validation_rule_pending_implementation", "kwargs": {}},
        ]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is True

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_nonexistent_column_reference(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Expectation referencing non-existent column should produce error."""
        expectations = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "nonexistent_col"},
            }
        ]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("nonexistent_col" in e for e in errors)

    @patch("tablespec.validator.GXSuiteExecutor", None)
    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_meta_prefix_columns_skipped(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Columns with meta_ or source_ prefix should not trigger missing column errors."""
        expectations = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "meta_ingestion_ts"},
            },
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "source_file_name"},
            },
        ]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is True

    @pytest.mark.filterwarnings(
        "ignore:ValidationRules contains ingested-stage expectations"
    )
    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_column_list_references_validated(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """column_list, column_A, column_B, column_set kwargs should be validated."""
        expectations = [
            {
                "type": "expect_compound_columns_to_be_unique",
                "kwargs": {"column_list": ["id", "missing_a"]},
            },
            {
                "type": "expect_column_pair_values_to_be_equal",
                "kwargs": {"column_A": "id", "column_B": "missing_b"},
            },
        ]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("missing_a" in e for e in errors)
        assert any("missing_b" in e for e in errors)

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_table_reference_validation(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """expect_table_row_count_to_equal_other_table should validate table refs."""
        expectations = [
            {
                "type": "expect_table_row_count_to_equal_other_table",
                "kwargs": {"other_table_name": "nonexistent_table"},
            },
        ]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("nonexistent_table" in e for e in errors)

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_missing_other_table_name_param(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Missing other_table_name param should produce error."""
        expectations = [
            {
                "type": "expect_table_row_count_to_equal_other_table",
                "kwargs": {},
            },
        ]
        umf = _make_umf(validation_rules=ValidationRules(expectations=expectations))
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("Missing required parameter" in e for e in errors)

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_completeness_checks_disabled(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """With check_completeness=False, completeness validators should not be called."""
        umf = _make_umf()
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx, check_completeness=False)
        assert success is True
        mock_prov.assert_not_called()
        mock_domain.assert_not_called()
        mock_base.assert_not_called()

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns")
    @patch("tablespec.validator.validate_domain_types")
    @patch("tablespec.validator.validate_baseline_expectations")
    def test_completeness_errors_reported(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Completeness errors should be surfaced."""
        mock_prov.return_value = [("meta_col", "Missing required provenance column")]
        mock_domain.return_value = [("col1", "Invalid domain type")]
        mock_base.return_value = [("col2", "Missing baseline expectation")]
        umf = _make_umf()
        ctx = self._make_context(umf)

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("Provenance" in e for e in errors)
        assert any("Domain type" in e for e in errors)
        assert any("Baseline" in e for e in errors)

    def test_file_not_found_handled(self, tmp_path):
        """FileNotFoundError should be caught and reported."""
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.side_effect = FileNotFoundError("table.yaml not found")

        missing = tmp_path / "nonexistent.yaml"

        success, errors = validate_table(missing, ctx)
        assert success is False
        assert any("File error" in e for e in errors)

    def test_generic_exception_handled(self, tmp_path):
        """Generic exceptions should be caught and reported."""
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.side_effect = RuntimeError("something broke")

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx)
        assert success is False
        assert any("Validation error" in e for e in errors)

    def test_pydantic_validation_error_verbose(self, tmp_path):
        """Pydantic ValidationError should show details in verbose mode."""
        from pydantic import ValidationError

        ctx = ValidationContext()
        ctx.converter = MagicMock()
        # Create a real ValidationError
        try:
            UMF(table_name="", version="bad", columns=[])
        except ValidationError as e:
            ctx.converter.load.side_effect = e

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx, verbose=True)
        assert success is False
        assert len(errors) > 1  # verbose shows individual errors

    def test_pydantic_validation_error_non_verbose(self, tmp_path):
        """Pydantic ValidationError should show summary in non-verbose mode."""
        from pydantic import ValidationError

        ctx = ValidationContext()
        ctx.converter = MagicMock()
        try:
            UMF(table_name="", version="bad", columns=[])
        except ValidationError as e:
            ctx.converter.load.side_effect = e

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        success, errors = validate_table(table_file, ctx, verbose=False)
        assert success is False
        assert len(errors) == 1
        assert "validation errors found" in errors[0]


# ---------------------------------------------------------------------------
# validate_pipeline
# ---------------------------------------------------------------------------


class TestValidatePipeline:
    """Tests for validate_pipeline function."""

    @patch("tablespec.validator.validate_table")
    def test_empty_directory(self, mock_validate, tmp_path):
        """Pipeline dir with no subdirectories should return empty results."""
        ctx = ValidationContext()
        results = validate_pipeline(tmp_path, ctx)
        assert results == {}
        mock_validate.assert_not_called()

    @patch("tablespec.validator.validate_naming_conventions", return_value=[])
    @patch("tablespec.validator.validate_provenance_columns", return_value=[])
    @patch("tablespec.validator.validate_domain_types", return_value=[])
    @patch("tablespec.validator.validate_baseline_expectations", return_value=[])
    def test_loads_all_table_dirs(
        self, mock_base, mock_domain, mock_prov, mock_naming, tmp_path
    ):
        """Pipeline validation should process each subdirectory with table.yaml."""
        # Create table directories
        for name in ["table_a", "table_b"]:
            d = tmp_path / name
            d.mkdir()
            (d / "table.yaml").write_text("dummy")

        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.validate_filename_pattern.return_value = []

        umf_a = _make_umf(table_name="table_a")
        umf_b = _make_umf(table_name="table_b")
        ctx.converter.load.side_effect = [umf_a, umf_b, umf_a, umf_b]

        results = validate_pipeline(tmp_path, ctx)
        assert "table_a" in results
        assert "table_b" in results

    def test_skips_hidden_directories(self, tmp_path):
        """Directories starting with . should be skipped."""
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "table.yaml").write_text("dummy")

        ctx = ValidationContext()
        results = validate_pipeline(tmp_path, ctx)
        assert results == {}

    def test_skips_dirs_without_table_yaml(self, tmp_path):
        """Directories without table.yaml should be skipped."""
        d = tmp_path / "not_a_table"
        d.mkdir()
        (d / "readme.md").write_text("not a table")

        ctx = ValidationContext()
        results = validate_pipeline(tmp_path, ctx)
        assert results == {}

    def test_load_failure_recorded(self, tmp_path):
        """Failure to load a table UMF should be recorded in results."""
        d = tmp_path / "broken_table"
        d.mkdir()
        (d / "table.yaml").write_text("dummy")

        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.side_effect = RuntimeError("corrupt file")

        results = validate_pipeline(tmp_path, ctx)
        assert "broken_table" in results
        assert any("Failed to load" in e for e in results["broken_table"])


# ---------------------------------------------------------------------------
# show_table_info
# ---------------------------------------------------------------------------


class TestShowTableInfo:
    """Tests for show_table_info function."""

    def test_basic_info(self, tmp_path):
        """Should return structured table info."""
        umf = _make_umf(table_name="my_table")
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        info = show_table_info(table_file, ctx)
        assert info["table_name"] == "my_table"
        assert info["version"] == "1.0"
        assert info["columns"]["total"] == 2
        assert info["validation"]["has_rules"] is False
        assert info["validation"]["expectation_count"] == 0
        assert info["relationships"]["foreign_keys"] == 0
        assert info["derivations"]["has_mappings"] is False

    def test_info_with_relationships(self, tmp_path):
        """Should report FK count when relationships are present."""
        fk = ForeignKey(
            column="cust_id", references_table="customers", references_column="id"
        )
        umf = _make_umf(
            relationships=Relationships(foreign_keys=[fk]),
        )
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        info = show_table_info(table_file, ctx)
        assert info["relationships"]["foreign_keys"] == 1

    def test_info_with_expectations(self, tmp_path):
        """Should report expectation count."""
        umf = _make_umf(
            validation_rules=ValidationRules(
                expectations=[
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    }
                ]
            ),
        )
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        info = show_table_info(table_file, ctx)
        assert info["validation"]["has_rules"] is True
        assert info["validation"]["expectation_count"] == 1

    def test_info_with_derivations(self, tmp_path):
        """Should report derivation mappings."""
        umf = _make_umf(derivations={"mappings": {"col1": {}, "col2": {}}})
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        table_file = tmp_path / "test.yaml"
        table_file.write_text("dummy")

        info = show_table_info(table_file, ctx)
        assert info["derivations"]["has_mappings"] is True
        assert info["derivations"]["mapping_count"] == 2


# ---------------------------------------------------------------------------
# convert_table
# ---------------------------------------------------------------------------


class TestConvertTable:
    """Tests for convert_table function."""

    def test_auto_detect_json(self, tmp_path):
        """Target format should auto-detect as JSON for .json suffix."""
        from tablespec.umf_loader import UMFFormat

        umf = _make_umf()
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        source = tmp_path / "source.yaml"
        source.write_text("dummy")
        dest = tmp_path / "output.json"

        convert_table(source, dest, context=ctx)
        ctx.converter.save.assert_called_once_with(umf, dest, UMFFormat.JSON)

    def test_auto_detect_split(self, tmp_path):
        """Target format should default to SPLIT for non-json destinations."""
        from tablespec.umf_loader import UMFFormat

        umf = _make_umf()
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        source = tmp_path / "source.yaml"
        source.write_text("dummy")
        dest = tmp_path / "output_dir"

        convert_table(source, dest, context=ctx)
        ctx.converter.save.assert_called_once_with(umf, dest, UMFFormat.SPLIT)

    def test_explicit_format(self, tmp_path):
        """Explicit target format should override auto-detection."""
        from tablespec.umf_loader import UMFFormat

        umf = _make_umf()
        ctx = ValidationContext()
        ctx.converter = MagicMock()
        ctx.converter.load.return_value = umf

        source = tmp_path / "source.yaml"
        source.write_text("dummy")
        dest = tmp_path / "output.json"

        convert_table(source, dest, target_format=UMFFormat.SPLIT, context=ctx)
        ctx.converter.save.assert_called_once_with(umf, dest, UMFFormat.SPLIT)

    def test_creates_context_if_none(self, tmp_path):
        """Should create a new context if none provided."""
        source = tmp_path / "source.yaml"
        source.write_text("dummy")
        dest = tmp_path / "output.json"

        with patch("tablespec.validator.ValidationContext") as mock_ctx_cls:
            mock_ctx = MagicMock()
            mock_ctx.load_umf.return_value = _make_umf()
            mock_ctx_cls.return_value = mock_ctx
            convert_table(source, dest)
            mock_ctx.load_umf.assert_called_once()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestGetRuleIdentifier:
    """Tests for _get_rule_identifier."""

    def test_with_column(self):
        exp = {
            "type": "expect_column_values_to_not_be_null",
            "kwargs": {"column": "name"},
            "meta": {"rule_index": 3},
        }
        result = _get_rule_identifier(exp, "orders")
        assert result == "orders.name.column_values_to_not_be_null.3"

    def test_without_column(self):
        exp = {
            "type": "expect_table_row_count_to_be_between",
            "kwargs": {},
            "meta": {"rule_index": 1},
        }
        result = _get_rule_identifier(exp, "orders")
        assert result == "orders.table_row_count_to_be_between.1"

    def test_missing_meta(self):
        exp = {"type": "expect_column_values_to_be_unique", "kwargs": {"column": "id"}}
        result = _get_rule_identifier(exp, "t")
        assert result == "t.id.column_values_to_be_unique.0"

    def test_dash_column_treated_as_no_column(self):
        exp = {
            "type": "expect_something",
            "kwargs": {"column": "-"},
            "meta": {"rule_index": 0},
        }
        result = _get_rule_identifier(exp, "t")
        assert result == "t.something.0"


class TestGroupChangesByNote:
    """Tests for _group_changes_by_note."""

    def _make_change(self, key: str):
        change = MagicMock()
        change.get_key.return_value = key
        return change

    def test_groups_by_review_note(self):
        c1 = self._make_change("col.a")
        c2 = self._make_change("col.b")
        notes = {"col.a": "Fix typo", "col.b": "Fix typo"}
        groups = _group_changes_by_note([c1, c2], notes)
        assert "Fix typo" in groups
        assert len(groups["Fix typo"]) == 2

    def test_changes_without_notes_get_default(self):
        c1 = self._make_change("col.a")
        groups = _group_changes_by_note([c1], {})
        assert "Update from Excel import" in groups
        assert len(groups["Update from Excel import"]) == 1

    def test_mixed_noted_and_unnoted(self):
        c1 = self._make_change("col.a")
        c2 = self._make_change("col.b")
        notes = {"col.a": "Specific note"}
        groups = _group_changes_by_note([c1, c2], notes)
        assert "Specific note" in groups
        assert "Update from Excel import" in groups


class TestFormatChangeDetails:
    """Tests for _format_change_details."""

    def test_empty_changes(self):
        assert _format_change_details([], "t") == ""

    def test_formats_bullet_list(self):
        c1 = MagicMock()
        c1.description.return_value = "Added column foo"
        c2 = MagicMock()
        c2.description.return_value = "Modified column bar"
        result = _format_change_details([c1, c2], "orders")
        assert "Changes in orders:" in result
        assert "- Added column foo" in result
        assert "- Modified column bar" in result


class TestGetSavedFiles:
    """Tests for _get_saved_files."""

    def test_split_format_dir(self, tmp_path):
        from tablespec.umf_loader import UMFFormat

        (tmp_path / "table.yaml").write_text("x")
        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "col1.yaml").write_text("x")

        files = _get_saved_files(tmp_path, UMFFormat.SPLIT)
        assert len(files) >= 1
        assert any(f.suffix == ".yaml" for f in files)

    def test_json_format(self, tmp_path):
        from tablespec.umf_loader import UMFFormat

        dest = tmp_path / "out.json"
        files = _get_saved_files(dest, UMFFormat.JSON)
        assert files == [dest]
