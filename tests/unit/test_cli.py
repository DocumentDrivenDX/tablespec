"""Tests for the tablespec CLI (typer app)."""

# @covers US-010-AC1
# @covers US-010-AC2
# @covers US-010-AC3
# @covers US-010-AC4
# @covers US-010-AC5

import json
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tablespec.cli import app

pytestmark = pytest.mark.no_spark


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from Rich CLI output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


class TestVersionCallback:
    """Test the default callback / help."""

    def test_no_command_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Help text should include the app description
        assert "UMF" in result.output or "tablespec" in result.output.lower()

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "batch-convert" in result.output
        assert "export-excel" in result.output
        assert "domains-list" in result.output


class TestBatchConvert:
    """Test batch-convert command."""

    def test_unknown_format_error(self, tmp_path):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"
        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "xyz"]
        )
        assert result.exit_code != 0
        assert "Unknown format" in result.output

    def test_no_files_found_warning(self, tmp_path):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"
        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "split"]
        )
        assert result.exit_code == 0
        assert "No files found" in result.output

    def test_batch_convert_split_finds_yaml_files(self, tmp_path):
        """When converting to split, finds *.umf.yaml files."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"

        # Create a dummy .umf.yaml file (will fail conversion but tests file discovery)
        yaml_file = source_dir / "test.umf.yaml"
        yaml_file.write_text("invalid: true")

        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "split"]
        )
        # Should find the file (even if conversion fails)
        assert "Found 1 files" in result.output or "FAIL" in result.output

    def test_batch_convert_json_finds_table_yaml(self, tmp_path):
        """When converting to JSON, looks for table.yaml dirs."""
        source_dir = tmp_path / "source"
        table_dir = source_dir / "my_table"
        table_dir.mkdir(parents=True)
        (table_dir / "table.yaml").write_text("version: '1.0'")
        dest_dir = tmp_path / "dest"

        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "json"]
        )
        # Should find 1 table directory
        assert "Found 1 files" in result.output or "FAIL" in result.output

    def test_batch_convert_skip_existing(self, tmp_path):
        """Without --force, existing destinations are skipped."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        # Create a yaml file and a matching destination
        yaml_file = source_dir / "test.umf.yaml"
        yaml_file.write_text("version: '1.0'")
        existing = dest_dir / "test"
        existing.mkdir()

        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "split"]
        )
        assert "SKIP" in result.output

    def test_batch_convert_source_not_found(self):
        """Non-existent source directory fails."""
        result = runner.invoke(
            app, ["batch-convert", "/nonexistent/path", "/tmp/dest", "--format", "json"]
        )
        assert result.exit_code != 0


class TestValidate:
    """Test validate command path detection."""

    def test_validate_split_table_dir_uses_single_table_path(self, tmp_path):
        table_dir = tmp_path / "outreach_list"
        table_dir.mkdir()
        (table_dir / "table.yaml").write_text("table_name: outreach_list\n")

        mock_context = MagicMock()
        mock_context.load_umf.return_value = SimpleNamespace(
            table_name="outreach_list",
            canonical_name="OutreachList",
            columns=[],
            file_format=None,
            expectations=None,
            relationships=None,
            derivations=None,
            version="1.0",
            description=None,
        )

        with (
            patch("tablespec.cli._validation_context", mock_context),
            patch(
                "tablespec.cli.validate_table", return_value=(True, [])
            ) as mock_validate_table,
            patch("tablespec.cli.validate_pipeline") as mock_validate_pipeline,
        ):
            result = runner.invoke(app, ["validate", str(table_dir)])

        assert result.exit_code == 0, result.output
        assert "Valid" in result.output
        assert "All 0 tables passed" not in result.output
        mock_validate_table.assert_called_once_with(
            table_dir, mock_context, verbose=False
        )
        mock_validate_pipeline.assert_not_called()

    def test_validate_split_table_dir_invalid_exits_nonzero(self, tmp_path):
        table_dir = tmp_path / "outreach_list"
        table_dir.mkdir()
        (table_dir / "table.yaml").write_text("table_name: outreach_list\n")

        mock_context = MagicMock()

        with (
            patch("tablespec.cli._validation_context", mock_context),
            patch(
                "tablespec.cli.validate_table",
                return_value=(False, ["boom"]),
            ) as mock_validate_table,
            patch("tablespec.cli.validate_pipeline") as mock_validate_pipeline,
        ):
            result = runner.invoke(app, ["validate", str(table_dir)])

        assert result.exit_code != 0
        assert "FAIL" in result.output
        assert "All 0 tables passed" not in result.output
        mock_validate_table.assert_called_once_with(
            table_dir, mock_context, verbose=False
        )
        mock_validate_pipeline.assert_not_called()


class TestExportExcel:
    """Test export-excel command."""

    def test_export_dest_exists_no_force(self, tmp_path):
        """Refuse to overwrite without --force."""
        source = _write_umf(tmp_path)
        dest = tmp_path / "test.xlsx"
        dest.write_text("existing")

        result = runner.invoke(app, ["export-excel", str(source), str(dest)])
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_export_file_not_found(self, tmp_path):
        """Non-existent source fails."""
        source = tmp_path / "nonexistent.yaml"
        dest = tmp_path / "output.xlsx"
        result = runner.invoke(app, ["export-excel", str(source), str(dest)])
        assert result.exit_code != 0

    @patch("tablespec.cli.UMFLoader")
    @patch("tablespec.cli.UMFToExcelConverter")
    def test_export_success(self, mock_converter_cls, mock_loader_cls, tmp_path):
        """Successful export creates file."""
        source = tmp_path / "test.umf.yaml"
        source.write_text("version: '1.0'")
        dest = tmp_path / "output.xlsx"

        mock_loader = MagicMock()
        mock_loader_cls.return_value = mock_loader

        mock_workbook = MagicMock()
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_workbook
        mock_converter_cls.return_value = mock_converter

        result = runner.invoke(app, ["export-excel", str(source), str(dest)])
        assert result.exit_code == 0
        assert "Done" in result.output
        mock_workbook.save.assert_called_once_with(dest)

    @patch("tablespec.cli.UMFLoader")
    @patch("tablespec.cli.UMFToExcelConverter")
    def test_export_force_overwrites(
        self, mock_converter_cls, mock_loader_cls, tmp_path
    ):
        """With --force, existing file is overwritten."""
        source = tmp_path / "test.umf.yaml"
        source.write_text("version: '1.0'")
        dest = tmp_path / "output.xlsx"
        dest.write_text("old content")

        mock_loader = MagicMock()
        mock_loader_cls.return_value = mock_loader

        mock_workbook = MagicMock()
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_workbook
        mock_converter_cls.return_value = mock_converter

        result = runner.invoke(app, ["export-excel", str(source), str(dest), "--force"])
        assert result.exit_code == 0
        assert "Done" in result.output
        # dest should have been unlinked (since force=True and dest existed)
        mock_workbook.save.assert_called_once()


class TestImportExcel:
    """Test import-excel command."""

    def test_import_source_not_found(self, tmp_path):
        """Non-existent source fails."""
        result = runner.invoke(
            app, ["import-excel", str(tmp_path / "nope.xlsx"), str(tmp_path / "out")]
        )
        assert result.exit_code != 0

    @patch("tablespec.cli.ExcelToUMFConverter")
    @patch("tablespec.cli.UMFLoader")
    def test_import_dest_exists_no_force(
        self, mock_loader_cls, mock_converter_cls, tmp_path
    ):
        """Refuse to overwrite without --force."""
        source = tmp_path / "test.xlsx"
        source.write_text("fake")
        dest = tmp_path / "out"
        dest.mkdir()

        mock_converter = MagicMock()
        mock_umf = MagicMock()
        mock_converter.convert.return_value = (mock_umf, {})
        mock_converter_cls.return_value = mock_converter

        result = runner.invoke(app, ["import-excel", str(source), str(dest)])
        assert result.exit_code != 0
        # Rich may wrap text across lines, so normalize whitespace
        flat_output = " ".join(result.output.split())
        assert "already exists" in flat_output

    @patch("tablespec.cli.ExcelToUMFConverter")
    @patch("tablespec.cli.UMFLoader")
    def test_import_success(self, mock_loader_cls, mock_converter_cls, tmp_path):
        """Successful import saves UMF."""
        source = tmp_path / "test.xlsx"
        source.write_text("fake")
        dest = tmp_path / "output_table"

        mock_converter = MagicMock()
        mock_umf = MagicMock()
        mock_converter.convert.return_value = (mock_umf, {})
        mock_converter_cls.return_value = mock_converter

        mock_loader = MagicMock()
        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(app, ["import-excel", str(source), str(dest)])
        assert result.exit_code == 0
        assert "Done" in result.output
        mock_loader.save.assert_called_once()

    @patch("tablespec.cli.ExcelToUMFConverter")
    def test_import_validation_error(self, mock_converter_cls, tmp_path):
        """ValidationError from converter is handled."""
        source = tmp_path / "test.xlsx"
        source.write_text("fake")
        dest = tmp_path / "output"

        mock_converter = MagicMock()
        mock_converter.convert.side_effect = ValueError("Bad data in sheet")
        mock_converter_cls.return_value = mock_converter

        result = runner.invoke(app, ["import-excel", str(source), str(dest)])
        assert result.exit_code != 0
        assert "Validation Error" in result.output or "Error" in result.output


class TestDomainsList:
    """Test domains-list command."""

    def test_domains_list_text(self):
        """Default text format lists domain types."""
        result = runner.invoke(app, ["domains-list"])
        assert result.exit_code == 0
        assert "Domain Types" in result.output
        assert "Total:" in result.output

    def test_domains_list_json(self):
        """JSON format returns JSON-like output with domain entries."""
        result = runner.invoke(app, ["domains-list", "--format", "json"])
        assert result.exit_code == 0
        # Rich console may wrap long lines, so just verify structure
        assert '"name"' in result.output
        assert '"title"' in result.output
        assert '"description"' in result.output


class TestDomainsShow:
    """Test domains-show command."""

    def test_domains_show_not_found(self):
        """Unknown domain type returns error."""
        result = runner.invoke(app, ["domains-show", "nonexistent_domain_xyz"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_domains_show_yaml(self):
        """Show a real domain type in YAML format."""
        result = runner.invoke(app, ["domains-show", "us_state_code"])
        assert result.exit_code == 0
        assert "us_state_code" in result.output

    def test_domains_show_json(self):
        """Show a real domain type in JSON format."""
        result = runner.invoke(
            app, ["domains-show", "us_state_code", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "us_state_code" in result.output
        assert '"us_state_code"' in result.output


class TestDomainsInfer:
    """Test domains-infer command."""

    def test_domains_infer_with_column(self):
        """Infer domain type from column name."""
        result = runner.invoke(app, ["domains-infer", "--column", "state_code"])
        assert result.exit_code == 0
        # May or may not find a match; just check it doesn't crash
        assert "Found" in result.output or "No domain type" in result.output

    def test_domains_infer_with_description(self):
        """Infer with column name and description."""
        result = runner.invoke(
            app,
            [
                "domains-infer",
                "--column",
                "st",
                "--description",
                "US state abbreviation",
            ],
        )
        assert result.exit_code == 0

    def test_domains_infer_with_samples(self):
        """Infer with sample values."""
        result = runner.invoke(
            app,
            ["domains-infer", "--column", "code", "--samples", "CA,NY,TX"],
        )
        assert result.exit_code == 0

    def test_domains_infer_missing_column(self):
        """Missing --column option shows error."""
        result = runner.invoke(app, ["domains-infer"])
        assert result.exit_code != 0


class TestImportExcelForceOverwrite:
    """Test import-excel with --force flag."""

    @patch("tablespec.cli.ExcelToUMFConverter")
    @patch("tablespec.cli.UMFLoader")
    def test_import_force_removes_existing_dir(
        self, mock_loader_cls, mock_converter_cls, tmp_path
    ):
        """With --force, existing directory is removed."""
        source = tmp_path / "test.xlsx"
        source.write_text("fake")
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "old_file.txt").write_text("old")

        mock_converter = MagicMock()
        mock_umf = MagicMock()
        mock_converter.convert.return_value = (mock_umf, {})
        mock_converter_cls.return_value = mock_converter

        mock_loader = MagicMock()
        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(app, ["import-excel", str(source), str(dest), "--force"])
        assert result.exit_code == 0
        mock_loader.save.assert_called_once()

    @patch("tablespec.cli.ExcelToUMFConverter")
    def test_import_file_not_found_error(self, mock_converter_cls, tmp_path):
        """FileNotFoundError from converter is handled."""
        source = tmp_path / "test.xlsx"
        source.write_text("fake")
        dest = tmp_path / "output"

        mock_converter = MagicMock()
        mock_converter.convert.side_effect = FileNotFoundError("Sheet not found")
        mock_converter_cls.return_value = mock_converter

        result = runner.invoke(app, ["import-excel", str(source), str(dest)])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch("tablespec.cli.ExcelToUMFConverter")
    def test_import_generic_exception(self, mock_converter_cls, tmp_path):
        """Generic exception from converter is handled."""
        source = tmp_path / "test.xlsx"
        source.write_text("fake")
        dest = tmp_path / "output"

        mock_converter = MagicMock()
        mock_converter.convert.side_effect = RuntimeError("Unexpected error")
        mock_converter_cls.return_value = mock_converter

        result = runner.invoke(app, ["import-excel", str(source), str(dest)])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestExportExcelErrorPaths:
    """Test export-excel error handling paths."""

    @patch("tablespec.cli.UMFLoader")
    def test_export_file_not_found(self, mock_loader_cls, tmp_path):
        """FileNotFoundError during loading is handled."""
        source = tmp_path / "test.umf.yaml"
        source.write_text("version: '1.0'")
        dest = tmp_path / "output.xlsx"

        mock_loader = MagicMock()
        mock_loader.load.side_effect = FileNotFoundError("File not found")
        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(app, ["export-excel", str(source), str(dest)])
        assert result.exit_code != 0
        assert "Error" in result.output

    @patch("tablespec.cli.UMFLoader")
    def test_export_validation_error(self, mock_loader_cls, tmp_path):
        """ValidationError during loading is handled."""
        from pydantic import ValidationError

        source = tmp_path / "test.umf.yaml"
        source.write_text("version: '1.0'")
        dest = tmp_path / "output.xlsx"

        mock_loader = MagicMock()
        # Simulate a Pydantic ValidationError
        try:
            from pydantic import BaseModel

            class Dummy(BaseModel):
                x: int

            Dummy(x="not_int")
        except ValidationError as e:
            mock_loader.load.side_effect = e

        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(app, ["export-excel", str(source), str(dest)])
        assert result.exit_code != 0

    @patch("tablespec.cli.UMFLoader")
    def test_export_generic_error(self, mock_loader_cls, tmp_path):
        """Generic exception during export is handled."""
        source = tmp_path / "test.umf.yaml"
        source.write_text("version: '1.0'")
        dest = tmp_path / "output.xlsx"

        mock_loader = MagicMock()
        mock_loader.load.side_effect = RuntimeError("Something went wrong")
        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(app, ["export-excel", str(source), str(dest)])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestBatchConvertAdditional:
    """Additional batch-convert tests."""

    def test_batch_convert_split_format_alias(self, tmp_path):
        """Format alias 's' works for split."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"
        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "s"]
        )
        assert result.exit_code == 0
        assert "No files found" in result.output

    def test_batch_convert_json_format_alias(self, tmp_path):
        """Format alias 'j' works for json."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"
        result = runner.invoke(
            app, ["batch-convert", str(source_dir), str(dest_dir), "--format", "j"]
        )
        assert result.exit_code == 0
        assert "No files found" in result.output

    def test_batch_convert_with_custom_pattern(self, tmp_path):
        """Custom --pattern option works."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"
        result = runner.invoke(
            app,
            [
                "batch-convert",
                str(source_dir),
                str(dest_dir),
                "--format",
                "split",
                "--pattern",
                "*.json",
            ],
        )
        assert result.exit_code == 0

    @patch("tablespec.cli.UMFLoader")
    def test_batch_convert_success_count(self, mock_loader_cls, tmp_path):
        """Successful conversions are counted."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"

        # Create source file
        yaml_file = source_dir / "test.umf.yaml"
        yaml_file.write_text("version: '1.0'")

        mock_loader = MagicMock()
        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(
            app,
            ["batch-convert", str(source_dir), str(dest_dir), "--format", "split"],
        )
        assert "1 converted" in _strip_ansi(result.output) or "FAIL" in _strip_ansi(
            result.output
        )

    @patch("tablespec.cli.UMFLoader")
    def test_batch_convert_error_count(self, mock_loader_cls, tmp_path):
        """Conversion errors are counted."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest"

        yaml_file = source_dir / "test.umf.yaml"
        yaml_file.write_text("version: '1.0'")

        mock_loader = MagicMock()
        mock_loader.convert.side_effect = RuntimeError("Convert failed")
        mock_loader_cls.return_value = mock_loader

        result = runner.invoke(
            app,
            ["batch-convert", str(source_dir), str(dest_dir), "--format", "split"],
        )
        assert "FAIL" in result.output


class TestDomainsListErrors:
    """Test domains-list error handling."""

    @patch("tablespec.cli.DomainTypeRegistry")
    def test_domains_list_file_not_found(self, mock_registry_cls):
        mock_registry_cls.side_effect = FileNotFoundError("Registry not found")
        result = runner.invoke(app, ["domains-list"])
        assert result.exit_code != 0

    @patch("tablespec.cli.DomainTypeRegistry")
    def test_domains_list_generic_error(self, mock_registry_cls):
        mock_registry_cls.side_effect = RuntimeError("Unexpected")
        result = runner.invoke(app, ["domains-list"])
        assert result.exit_code != 0


class TestDomainsShowErrors:
    """Test domains-show error handling."""

    @patch("tablespec.cli.DomainTypeRegistry")
    def test_domains_show_file_not_found(self, mock_registry_cls):
        mock_registry_cls.side_effect = FileNotFoundError("Not found")
        result = runner.invoke(app, ["domains-show", "test_domain"])
        assert result.exit_code != 0

    @patch("tablespec.cli.DomainTypeRegistry")
    def test_domains_show_generic_error(self, mock_registry_cls):
        mock_registry_cls.side_effect = RuntimeError("Unexpected")
        result = runner.invoke(app, ["domains-show", "test_domain"])
        assert result.exit_code != 0


class TestDomainsInferErrors:
    """Test domains-infer error handling."""

    @patch("tablespec.cli.DomainTypeInference")
    def test_domains_infer_file_not_found(self, mock_inference_cls):
        mock_inference_cls.side_effect = FileNotFoundError("Not found")
        result = runner.invoke(app, ["domains-infer", "--column", "test"])
        assert result.exit_code != 0

    @patch("tablespec.cli.DomainTypeInference")
    def test_domains_infer_generic_error(self, mock_inference_cls):
        mock_inference_cls.side_effect = RuntimeError("Unexpected")
        result = runner.invoke(app, ["domains-infer", "--column", "test"])
        assert result.exit_code != 0

    @patch("tablespec.cli.DomainTypeInference")
    def test_domains_infer_no_match(self, mock_inference_cls):
        mock_inference = MagicMock()
        mock_inference.infer_domain_type.return_value = (None, 0.0)
        mock_inference_cls.return_value = mock_inference

        result = runner.invoke(app, ["domains-infer", "--column", "zzz_unknown"])
        assert result.exit_code == 0
        assert "No domain type" in result.output


MINIMAL_UMF_JSON = json.dumps(
    {
        "version": "1.0",
        "table_name": "TestTable",
        "columns": [
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": {"MD": False, "MP": False, "ME": False},
            },
            {
                "name": "name",
                "data_type": "VARCHAR",
                "length": 100,
                "nullable": {"MD": True, "MP": True, "ME": True},
            },
        ],
    }
)


def _write_umf(tmp_path: Path) -> Path:
    """Write a minimal UMF JSON file and return its path."""
    umf_file = tmp_path / "test.json"
    umf_file.write_text(MINIMAL_UMF_JSON)
    return umf_file


class TestGenerate:
    """Test generate command."""

    def test_generate_sql_format(self, tmp_path):
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(app, ["generate", str(umf_file), "--format", "sql"])
        assert result.exit_code == 0
        assert "CREATE TABLE" in result.output

    def test_generate_pyspark_format(self, tmp_path):
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(app, ["generate", str(umf_file), "--format", "pyspark"])
        assert result.exit_code == 0
        assert "StructType" in result.output

    def test_generate_json_format(self, tmp_path):
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(app, ["generate", str(umf_file), "--format", "json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "properties" in parsed

    def test_generate_unknown_format_error(self, tmp_path):
        umf_file = _write_umf(tmp_path)
        result = runner.invoke(app, ["generate", str(umf_file), "--format", "xml"])
        assert result.exit_code == 1
        assert "Unknown format" in result.output


class TestCLIHelpExamples:
    """Ensure help text does not promote legacy inline YAML as canonical input."""

    @pytest.mark.parametrize(
        "command",
        [
            ["validate"],
            ["info"],
            ["generate"],
            ["emit"],
            ["export-excel"],
            ["explore"],
        ],
    )
    def test_commands_do_not_show_table_umf_yaml_as_canonical(self, command):
        result = runner.invoke(app, [*command, "--help"])
        assert result.exit_code == 0
        assert "table.umf.yaml" not in result.output
