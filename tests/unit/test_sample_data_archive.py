"""Portable CSV pack export and CLI behavior, with no remote services."""

import csv
from io import StringIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.sample_data.archive import export_csv_zip
from tests.unit.test_legal_sample_data import dataset, EXAMPLE

pytestmark = pytest.mark.no_spark


def test_csv_archive_reproducible_complete_and_lossless(tmp_path: Path) -> None:
    data = dataset(tmp_path)
    try:
        left, right = tmp_path / "left.zip", tmp_path / "right.zip"
        export_csv_zip(data, left)
        export_csv_zip(data, right)
        assert left.read_bytes() == right.read_bytes()
        with ZipFile(left) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["null_value"] == "\\N"
            assert json.loads(archive.read("report.json")) == data.report
            for table in data.specs:
                assert (
                    json.loads(archive.read(f"schemas/{table}.json"))
                    == data.specs[table]
                )
                rows = list(
                    csv.DictReader(StringIO(archive.read(f"data/{table}.csv").decode()))
                )
                expected = [row for batch in data.batches(table) for row in batch]
                assert len(rows) == data.counts[table]
                for actual, original in zip(rows, expected, strict=True):
                    assert actual == {
                        key: "\\N" if value is None else str(value)
                        for key, value in original.items()
                        if key in actual
                    }
    finally:
        data.close()


def test_export_cli_requires_no_auth(tmp_path: Path) -> None:
    path = tmp_path / "legal.zip"
    result = CliRunner().invoke(
        app,
        [
            "sample-data",
            "export",
            "--umf",
            str(EXAMPLE),
            "--domain",
            "legal",
            "--output",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert path.is_file()


def test_archive_failure_preserves_existing_output(tmp_path: Path) -> None:
    data = dataset(tmp_path)
    output = tmp_path / "existing.zip"
    output.write_bytes(b"previous pack")
    try:
        data.verified = False
        with pytest.raises(ValueError, match="verification"):
            export_csv_zip(data, output)
        assert output.read_bytes() == b"previous pack"
    finally:
        data.close()


@pytest.mark.parametrize(
    "text",
    ["", "quote'", 'double"quote', "\\", "line\nnext\ttab", "nul\x00😀", "trailing\\"],
)
def test_csv_reader_preserves_awkward_strings_and_nulls(tmp_path, text):
    from tablespec.sample_data.archive import read_csv_rows

    path = tmp_path / "awkward.csv"
    spec = {
        "columns": [
            {"name": "value", "data_type": "STRING"},
            {"name": "optional", "data_type": "STRING"},
        ]
    }
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
        writer.writerow(["value", "optional"])
        writer.writerow([text, "\\N"])
    assert list(read_csv_rows(path, spec)) == [{"value": text, "optional": None}]


def test_csv_reader_refuses_invalid_source_shape_and_type(tmp_path):
    from tablespec.sample_data.archive import read_csv_rows

    path = tmp_path / "invalid.csv"
    spec = {"columns": [{"name": "value", "data_type": "INTEGER"}]}
    for content in ["wrong\n1\n", "value\n1,2\n", "value\nnot-a-number\n"]:
        path.write_text(content)
        with pytest.raises(ValueError):
            list(read_csv_rows(path, spec))


def test_csv_reader_refuses_floating_point_overflow(tmp_path):
    from tablespec.sample_data.archive import read_csv_rows

    path = tmp_path / "overflow.csv"
    path.write_text('"value"\n"1e9999"\n', encoding="utf-8")
    spec = {"columns": [{"name": "value", "data_type": "DOUBLE"}]}
    with pytest.raises(ValueError, match="declared type"):
        list(read_csv_rows(path, spec))


def test_explicit_pack_refuses_custom_generation_schema(tmp_path):
    """Independent --umf input cannot be silently replaced by pack schemas."""
    from copy import deepcopy
    from tablespec.sample_data.config import GenerationConfig
    from tablespec.sample_data.engine import SampleDataGenerator
    from tablespec.sample_data.streaming import GeneratedDataset

    pack = EXAMPLE.parent / "domain-pack.json"
    config = GenerationConfig(domain="legal", domain_pack_path=pack)
    specs = SampleDataGenerator(EXAMPLE, tmp_path, config).load_umf_files(strict=True)
    customized = deepcopy(specs)
    customized["clients"]["columns"][0]["description"] = "Caller supplied description"
    with pytest.raises(ValueError, match="Generation schema differs"):
        GeneratedDataset(
            tmp_path / "custom.sqlite", customized, dict.fromkeys(specs, 0), config
        )
    data = GeneratedDataset(
        tmp_path / "exact.sqlite", specs, dict.fromkeys(specs, 0), config
    )
    try:
        data.generate()
        data.specs["clients"]["columns"][0]["description"] = "Changed after admission"
        with pytest.raises(ValueError, match="Generation schema differs"):
            export_csv_zip(data, tmp_path / "output.zip")
        assert not (tmp_path / "output.zip").exists()
    finally:
        data.close()
