"""Official medical fixtures use the shared source ingestion and CSV pack path."""

import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.sample_data.archive import export_csv_zip, read_csv_rows
from tablespec.sample_data.ingest import ImportedDataset

pytestmark = pytest.mark.no_spark
EXAMPLE = Path(__file__).parents[2] / "examples" / "medical"


def imported(tmp_path):
    return ImportedDataset(tmp_path / "rows.sqlite", EXAMPLE / "domain-pack.json")


def test_official_medical_archive_retains_source_bytes_and_meaning(tmp_path):
    data = imported(tmp_path)
    try:
        assert data.verified
        assert data.counts == data.source_metadata["fixture_counts"]
        with pytest.raises(ValueError, match="synthetically"):
            data.generate()
        left, right = tmp_path / "left.zip", tmp_path / "right.zip"
        export_csv_zip(data, left)
        export_csv_zip(data, right)
        assert left.read_bytes() == right.read_bytes()
        with ZipFile(left) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["origin"] == "external"
            assert manifest["seed"] is None
            for reference, entry in manifest["schema_artifacts"].items():
                assert json.loads(archive.read(entry)) == json.loads(
                    (EXAMPLE / reference).read_text()
                )
            for reference, entry in manifest["source_artifacts"].items():
                assert archive.read(entry) == (EXAMPLE / reference).read_bytes()
        resources = {
            row["resource_key"]: row
            for batch in data.batches("resources")
            for row in batch
        }
        for row in resources.values():
            raw = (EXAMPLE / row["source_file"]).read_bytes()
            assert row["resource_json"].encode() == raw
            assert hashlib.sha256(raw).hexdigest() == row["source_sha256"]
        observations = {
            row["resource_key"]: row
            for batch in data.batches("observations")
            for row in batch
        }
        for key, row in observations.items():
            original = json.loads(resources[key]["resource_json"], parse_float=Decimal)
            assert Decimal(row["value_decimal"]) == original["valueQuantity"]["value"]
            assert json.loads(
                row["reference_ranges_json"], parse_float=Decimal
            ) == original.get("referenceRange", [])
            assert row["unit_code"] == original["valueQuantity"]["code"]
        assert (
            observations["Observation/body-height"]["effective_start"] == "1999-07-02"
        )
        assert (
            observations["Observation/body-height"]["value_decimal"]
            == "66.899999999999991"
        )
        references = [
            row for batch in data.batches("resource_references") for row in batch
        ]

        def native_references(value, pointer=""):
            if isinstance(value, dict):
                for key, child in value.items():
                    path = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                    if key == "reference" and isinstance(child, str):
                        yield path, child
                    else:
                        yield from native_references(child, path)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from native_references(child, pointer + "/" + str(index))

        expected_references = {
            (key, pointer, reference)
            for key, resource in resources.items()
            for pointer, reference in native_references(
                json.loads(resource["resource_json"])
            )
        }
        assert {
            (row["source_resource_key"], row["json_pointer"], row["native_reference"])
            for row in references
        } == expected_references
        for row in references:
            local = row["native_reference"] in resources
            assert row["resolution"] == ("local" if local else "unresolved")
            assert row["target_resource_key"] == (
                row["native_reference"] if local else None
            )
    finally:
        data.close()


@pytest.mark.parametrize(
    "failure",
    [
        "checksum",
        "rights",
        "orphan",
        "unique",
        "null",
        "escape",
        "schema_number",
        "schema_duplicate",
    ],
)
def test_source_ingestion_refuses_invalid_inputs_before_export(tmp_path, failure):
    root = tmp_path / "pack"
    shutil.copytree(EXAMPLE, root)
    metadata = json.loads((root / "domain-pack.json").read_text())
    source = metadata["sources"]["csv_patients"]
    path = root / source["reference"]
    if failure == "rights":
        source["license"]["redistribution"] = "unknown"
    elif failure == "escape":
        source["reference"] = "../outside.csv"
    elif failure == "checksum":
        path.write_text("changed")
    elif failure in ("schema_number", "schema_duplicate"):
        schema_path = root / "umf/patients.json"
        text = schema_path.read_text()
        addition = (
            '"future_numeric":0.10000000000000001,'
            if failure == "schema_number"
            else '"future_annotation":"first","future_annotation":"second",'
        )
        schema_path.write_text("{" + addition + text[1:])
    else:
        with path.open(newline="") as stream:
            rows = list(csv.reader(stream))
        if failure == "orphan":
            rows[1][4] = "Organization/missing"
        elif failure == "unique":
            rows.append(rows[1])
        else:
            rows[1][0] = "\\N"
        with path.open("w", newline="") as stream:
            csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(
                rows
            )
        source["checksum"]["value"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "domain-pack.json").write_text(json.dumps(metadata))
    with pytest.raises((ValueError, FileNotFoundError)):
        ImportedDataset(tmp_path / "invalid.sqlite", root / "domain-pack.json")


def test_ingest_cli_exports_and_dry_runs_without_auth(tmp_path):
    output = tmp_path / "medical.zip"
    result = CliRunner().invoke(
        app,
        [
            "sample-data",
            "ingest",
            "--pack",
            str(EXAMPLE / "domain-pack.json"),
            "--output",
            str(output),
            "--target",
            "sample_catalog.medical_demo",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert "USING DELTA" in result.output
    assert "COMMENT" in result.output


def test_csv_decimal_reader_is_exact(tmp_path):
    spec = {"columns": [{"name": "value", "data_type": "DECIMAL"}]}
    path = tmp_path / "exact.csv"
    path.write_text('"value"\n"1234567890123456.78"\n')
    assert list(read_csv_rows(path, spec)) == [
        {"value": Decimal("1234567890123456.78")}
    ]


def test_shared_decimal_ingestion_preserves_bounds_keys_and_38_digit_values(tmp_path):
    root = tmp_path / "decimal_pack"
    root.mkdir()

    def schema(name, columns, **extra):
        if "validation_rules" in extra:
            rules = extra.pop("validation_rules")
            extra["quality_checks"] = {
                "checks": [
                    {"expectation": rule, "severity": "error", "blocking": True}
                    for rule in rules
                    if rule["type"] == "expect_column_values_to_be_between"
                ]
            }
            extra["validation_rules"] = {
                "expectations": [
                    rule
                    for rule in rules
                    if rule["type"] != "expect_column_values_to_be_between"
                ]
            }
        return {
            "version": "1.0",
            "table_name": name,
            "columns": columns,
            **extra,
        }

    def decimal(name):
        return {
            "name": name,
            "data_type": "DECIMAL",
            "nullable": False,
            "precision": 38,
            "scale": 2,
        }

    specs = {
        "parents": schema("parents", [decimal("id")], primary_key=["id"]),
        "children": schema(
            "children",
            [decimal("parent_id")],
            relationships={
                "foreign_keys": [
                    {
                        "column": "parent_id",
                        "references_table": "parents",
                        "references_column": "id",
                    }
                ]
            },
        ),
        "amounts": schema(
            "amounts",
            [decimal("value")],
            primary_key=["value"],
            validation_rules=[
                {
                    "type": "expect_column_values_to_be_between",
                    "kwargs": {"column": "value", "min_value": 0.1, "max_value": 0.1},
                },
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "value", "value_set": [0.1]},
                },
            ],
        ),
        "large_values": schema("large_values", [decimal("value")]),
    }
    largest = "9" * 36 + ".12"
    rows = {
        "parents": '"id"\n"1.00"\n',
        "children": '"parent_id"\n"1.0"\n',
        "amounts": '"value"\n"0.10"\n',
        "large_values": f'"value"\n"{largest}"\n',
    }
    metadata = {
        "id": "decimal_fixture",
        "version": "1.0.0",
        "domain_types": {"exact_decimal": {"description": "Exact decimal fixture"}},
        "schemas": [],
        "sources": {},
        "source_bindings": [],
    }
    for name, spec in specs.items():
        (root / f"{name}.json").write_text(json.dumps(spec))
        raw = rows[name].encode()
        (root / f"{name}.csv").write_bytes(raw)
        metadata["schemas"].append(
            {"id": name, "format": "tablespec", "reference": f"{name}.json"}
        )
        metadata["sources"][name] = {
            "kind": "external",
            "data_kind": "fabricated",
            "format": "csv",
            "reference": f"{name}.csv",
            "license": {"redistribution": "allowed"},
            "checksum": {
                "algorithm": "sha256",
                "value": hashlib.sha256(raw).hexdigest(),
            },
        }
        metadata["source_bindings"].append(
            {"schema_id": name, "source_id": name, "role": "rows"}
        )
    pack_path = root / "pack.json"
    pack_path.write_text(json.dumps(metadata))
    data = ImportedDataset(tmp_path / "decimal.sqlite", pack_path)
    try:
        assert next(data.batches("amounts"))[0]["value"] == Decimal("0.1")
        assert next(data.batches("large_values"))[0]["value"] == Decimal(largest)
        assert data.report["children"]["fk_orphan_count"] == 0
    finally:
        data.close()
    # Different spellings of equal Decimal values must violate the same key.
    raw = rows["amounts"].encode() + b'"0.1"\n'
    (root / "amounts.csv").write_bytes(raw)
    metadata["sources"]["amounts"]["checksum"]["value"] = hashlib.sha256(
        raw
    ).hexdigest()
    pack_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Uniqueness"):
        ImportedDataset(tmp_path / "duplicate-decimal.sqlite", pack_path)
