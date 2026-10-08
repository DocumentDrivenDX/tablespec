"""Official Python UMF ownership and native compiler integration."""

import json
from pathlib import Path

import duckdb
import pytest
from umf import Document, read_document, validate_document

from tablespec.extensions.umf import (
    compiler_view,
    from_legacy,
    pipeline_registry,
    recover_sources,
    to_legacy,
)
from tablespec.models import UMF
from tablespec.schemas import (
    build_ingest_select,
    generate_ingest_sql,
    generate_json_schema,
    generate_sql_ddl,
)
from tablespec.umf_loader import UMFFormat, UMFLoader

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


@pytest.fixture
def native():
    return {
        "version": "1.0",
        "table_name": "orders",
        "primary_key": ["id"],
        "columns": [
            {"name": "id", "data_type": "INTEGER", "nullable": False},
            {"name": "amount", "data_type": "DECIMAL", "precision": 12, "scale": 2},
            {
                "name": "label",
                "data_type": "VARCHAR",
                "length": 20,
                "nullable": {"A": False, "B": True},
                "format": "retained prose",
            },
        ],
    }


def test_official_core_and_local_extension(native):
    document = from_legacy(native)
    assert type(document).__module__ == "umf.models"
    assert document.modules[0].elements[0].scalar_type == "integer"
    result = validate_document(document, pipeline_registry())
    assert result.valid and not result.complete
    assert to_legacy(document) == native
    assert (
        compiler_view(document).model_dump() == UMF.model_validate(native).model_dump()
    )


def test_author_core_directly_then_compile():
    document = Document.model_validate(
        {
            "umf": "0.8.0",
            "id": "authored",
            "vocabularies": {"tablespec.pipeline": {"version": "0.1.0"}},
            "modules": [
                {
                    "id": "orders",
                    "namespace": "orders",
                    "elements": [
                        {
                            "id": "id",
                            "kind": "field",
                            "name": "id",
                            "scalarType": "integer",
                            "extensions": {
                                "tablespec.pipeline": {
                                    "metadata": {"data_type": "INTEGER"}
                                }
                            },
                        },
                        {
                            "id": "label",
                            "kind": "field",
                            "name": "label",
                            "scalarType": "string",
                            "extensions": {
                                "tablespec.pipeline": {
                                    "metadata": {"data_type": "TEXT"}
                                }
                            },
                        },
                    ],
                }
            ],
        }
    )
    view = compiler_view(document)
    assert [column.data_type for column in view.columns] == ["INTEGER", "TEXT"]
    assert "CREATE TABLE" in generate_sql_ddl(view.model_dump(exclude_none=True))
    document.modules[0].elements[1].name = "title"
    assert compiler_view(document).columns[1].name == "title"


def test_native_unknown_content_preserved_but_not_executed(native, tmp_path):
    native["unfamiliar"] = {"meaning": None}
    native["columns"][0]["future"] = {"integerToken": "9007199254740993"}
    document = from_legacy(native)
    assert to_legacy(document) == native
    path = tmp_path / "orders.umf.json"
    UMFLoader().save_document(document, path)
    assert read_document(path.read_text()).to_dict() == document.to_dict()
    with pytest.raises(ValueError):
        compiler_view(document)


def test_shared_unknown_content_survives_normal_load_save(native, tmp_path):
    document = from_legacy(native)
    data = document.to_dict()
    data["vocabularies"]["future"] = {"version": "1.0.0"}
    data["extensions"] = {
        "future": {"null": None, "decimalToken": "1.000000000000000001"}
    }
    document = Document.model_validate(data)
    loader = UMFLoader()
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    loader.save_document(document, source)
    view = loader.load(source)
    loader.save(view, target, UMFFormat.JSON)
    assert loader.load_document(target).to_dict() == data
    with pytest.raises(ValueError, match="Shared UMF"):
        loader.save(view, tmp_path / "split")
    view.columns[0].description = "unsynchronized change"
    with pytest.raises(ValueError, match="Derived compiler view"):
        loader.save_json(view, target)
    assert loader.load_document(target).to_dict() == data


@pytest.mark.parametrize(
    "property,value",
    [
        ("allowedValues", [{"integerToken": "1"}]),
        ("default", {"value": {"integerToken": "1"}, "on": "missing"}),
        ("nullability", "required"),
        ("facets", {"integerWidth": {"bits": 64, "signed": True}}),
    ],
)
def test_unsupported_execution_semantics_refuse(native, property, value):
    data = from_legacy(native).to_dict()
    data["modules"][0]["elements"][0][property] = value
    document = Document.model_validate(data)
    with pytest.raises(ValueError, match="Unsupported core properties"):
        compiler_view(document)


def test_scalar_refinement_conflict_refuses(native):
    document = from_legacy(native)
    document.modules[0].elements[0].scalar_type = "string"
    with pytest.raises(ValueError, match="disagree"):
        compiler_view(document)


def test_missing_native_binding_and_unknown_nested_policy_refuse(native):
    document = from_legacy(native)
    document.modules[0].elements[0].extensions["tablespec.pipeline"]["metadata"].pop(
        "data_type"
    )
    with pytest.raises(ValueError, match="Explicit TableSpec"):
        compiler_view(document)
    native["columns"][0]["derivation"] = {"expression": "1", "future_rule": True}
    with pytest.raises(ValueError, match="Unknown native model fields"):
        compiler_view(from_legacy(native))


def test_shared_json_cli_runs_existing_generator(native, tmp_path):
    from typer.testing import CliRunner

    from tablespec.cli import app

    path = tmp_path / "orders.umf.json"
    UMFLoader().save_document(from_legacy(native), path)
    result = CliRunner().invoke(app, ["generate", str(path), "--format", "ingest"])
    assert result.exit_code == 0, result.output
    assert "raw_orders" in result.output and "ingested_orders" in result.output


def test_migration_rejects_numeric_loss_and_archive_mutation(native, tmp_path):
    path = tmp_path / "legacy.json"
    text = json.dumps(native).replace(
        '"precision": 12', '"precision": 0.10000000000000001'
    )
    path.write_text(text)
    with pytest.raises(ValueError, match="decimal value"):
        UMFLoader().load_document(path)
    assert path.read_text() == text
    path.write_text(json.dumps(native))
    document = UMFLoader().load_document(path)
    document.extensions["tablespec.source-archive"]["files"][path.name] = "changed"
    with pytest.raises(ValueError, match="files changed"):
        recover_sources(document)


@pytest.mark.parametrize("format", ["json", "inline", "split"])
def test_source_archive_and_explicit_rollback(native, tmp_path, format):
    loader = UMFLoader()
    if format == "json":
        source = tmp_path / "legacy.json"
        source.write_text(json.dumps(native, indent=4) + "\n")
        expected = {source.name: source.read_text()}
    elif format == "inline":
        source = tmp_path / "legacy.yaml"
        source.write_text(json.dumps(native, indent=3))
        expected = {source.name: source.read_text()}
    else:
        source = tmp_path / "legacy"
        loader.save(UMF.model_validate(native), source)
        (source / "opaque.txt").write_text("uninterpreted sidecar\n")
        expected = {
            p.relative_to(source).as_posix(): p.read_text()
            for p in source.rglob("*")
            if p.is_file()
        }
    document = loader.load_document(source)
    assert recover_sources(document) == expected
    persisted = tmp_path / "shared.json"
    loader.save_document(document, persisted)
    assert recover_sources(loader.load_document(persisted)) == expected
    document.modules[0].elements[0].description = "changed"
    with pytest.raises(ValueError, match="changed since migration"):
        recover_sources(document)


def test_existing_golden_ingest_compilation_from_shared_documents():
    loader = UMFLoader()
    root = Path(__file__).parents[1] / "golden/ingest_sql"
    for path in root.glob("*.input.yaml"):
        data = loader._convert_yaml_to_plain_strings(loader.yaml.load(path.read_text()))
        data.setdefault("version", "1.0")
        legacy = UMF.model_validate(data)
        shared = UMF.from_document(legacy.to_document())
        assert generate_ingest_sql(
            shared.model_dump(exclude_none=True)
        ) == generate_ingest_sql(legacy.model_dump(exclude_none=True))
        assert generate_json_schema(
            shared.model_dump(exclude_none=True)
        ) == generate_json_schema(legacy.model_dump(exclude_none=True))


def test_synthetic_ingest_rows_from_shared_document(native):
    legacy = UMF.model_validate(native)
    view = UMF.from_document(legacy.to_document())
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE raw_orders(id VARCHAR, amount VARCHAR, label VARCHAR)"
        )
        connection.execute(
            "INSERT INTO raw_orders VALUES ('1','12.34','one'),('2',NULL,'two'),('bad','-1.20','bad')"
        )
        for model in (legacy, view):
            plan = build_ingest_select(
                model.model_dump(exclude_none=True), dialect="duckdb"
            )
            rows = connection.execute(
                "SELECT " + plan.select_block + " FROM raw_orders"
            ).fetchall()
            assert [
                (row[0], str(row[1]) if row[1] is not None else None, row[2])
                for row in rows
            ] == [(1, "12.34", "one"), (2, None, "two"), (None, "-1.20", "bad")]


def test_compile_orchestrator_preserves_shared_snapshot_and_runtime_source(
    native, tmp_path
):
    from umf import Vocabulary

    from tablespec.e2e.backbone import _declared_source
    from tablespec.e2e.compile import compile_umfs

    native["source"] = {"kind": "delimited", "delimiter": "|"}
    legacy = UMF.model_validate(native)
    document = legacy.to_document()
    document.vocabularies["future"] = Vocabulary(version="1.0.0")
    shared = UMF.from_document(document)
    original = compile_umfs([legacy], tmp_path / "native", source="specs").table(
        "orders"
    )
    compiled = compile_umfs([shared], tmp_path / "shared", source="specs").table(
        "orders"
    )
    for field in (
        "ingest_sql",
        "ddl_sql",
        "pyspark_schema",
        "json_schema",
        "suite_json",
    ):
        assert (
            getattr(original, field).read_text() == getattr(compiled, field).read_text()
        )
    snapshot = UMFLoader().load_document(compiled.umf_snapshot)
    assert snapshot.to_dict() == document.to_dict()
    assert _declared_source(compiled.umf_snapshot).delimiter == "|"
