"""All-pack semantics and replay use reviewed checks, not executable pack SQL."""

from decimal import Decimal
import json
from pathlib import Path
import shutil
import sqlite3
from zipfile import ZipFile

import pytest

from tablespec.sample_data.archive import export_csv_zip, read_csv_rows
from tablespec.sample_data.ingest import ImportedDataset
from tablespec.sample_data.replay import ReplayDataset

pytestmark = pytest.mark.no_spark
ROOT = Path(__file__).parents[2]
PACKS = ROOT / "examples" / "domain-packs"
REVIEWED = json.loads(
    (ROOT / "tests/fixtures/domain-packs/reviewed-checks.json").read_text()
)


def isolated_checks(data, reviewed):
    database = sqlite3.connect(":memory:")
    try:
        for name, spec in data.specs.items():
            definitions = ",".join(
                f'"{c["name"]}" {c["data_type"]}' for c in spec["columns"]
            )
            database.execute(f'CREATE TABLE "{name}" ({definitions})')
            columns = [c["name"] for c in spec["columns"]]
            for batch in data.batches(name):
                for row in batch:
                    values = [
                        str(row[c]) if isinstance(row[c], Decimal) else row[c]
                        for c in columns
                    ]
                    database.execute(
                        f'INSERT INTO "{name}" VALUES ({",".join("?" for _ in values)})',
                        values,
                    )

        def authorize(action, arg1, arg2, database_name, trigger):
            if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and arg2 in {
                "count",
                "sum",
                "min",
                "max",
                "abs",
            }:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        database.set_authorizer(authorize)
        calls = [0]

        def budget():
            calls[0] += 1
            return int(calls[0] > 10000)

        database.set_progress_handler(budget, 100)
        assert data.source_metadata["scenario_checks"] == reviewed["checks"]
        for check in reviewed["checks"]:
            assert [
                list(row) for row in database.execute(check["sql"]).fetchall()
            ] == check["expected"], check["id"]
        with pytest.raises(sqlite3.DatabaseError):
            database.execute("SELECT load_extension('/tmp/evil')")
        with pytest.raises(sqlite3.DatabaseError):
            database.execute("ATTACH DATABASE '/tmp/evil.db' AS evil")
    finally:
        database.close()


@pytest.mark.parametrize("name", sorted(REVIEWED))
def test_domain_scenarios_and_every_fixture_field(name, tmp_path):
    """@covers US-063-AC2 @covers US-063-AC3 @covers US-064-AC2 @covers US-064-AC3
    @covers US-065-AC2 @covers US-065-AC3 @covers US-066-AC2 @covers US-066-AC3
    @covers US-067-AC2 @covers US-067-AC3 @covers US-068-AC2 @covers US-068-AC3
    @covers US-069-AC2 @covers US-069-AC3 @covers US-070-AC2 @covers US-070-AC3
    @covers US-071-AC2 @covers US-071-AC3 @covers US-072-AC2 @covers US-072-AC3
    @covers US-073-AC2 @covers US-073-AC3 @covers US-074-AC2 @covers US-074-AC3
    @covers US-075-AC2 @covers US-075-AC3 @covers US-076-AC2 @covers US-076-AC3
    """
    pack = PACKS / name / "domain-pack.json"
    data = ImportedDataset(tmp_path / "rows.sqlite", pack)
    try:
        isolated_checks(data, REVIEWED[name])
        for table in REVIEWED[name]["tables"]:
            rows = [row for batch in data.batches(table["name"]) for row in batch]
            columns = [c["name"] for c in data.specs[table["name"]]["columns"]]
            actual = [
                [None if row[col] is None else str(row[col]) for col in columns]
                for row in rows
            ]
            expected = [
                [None if value is None else str(value) for value in row]
                for row in table["rows"]
            ]
            # Decimal canonical spelling can remove insignificant zeroes; compare values exactly.
            for got, want in zip(actual, expected, strict=True):
                for index, column in enumerate(data.specs[table["name"]]["columns"]):
                    if column["data_type"] == "DECIMAL" and got[index] is not None:
                        assert Decimal(got[index]) == Decimal(want[index])
                    else:
                        assert got[index] == want[index]
    finally:
        data.close()


@pytest.mark.parametrize("name", sorted(REVIEWED))
def test_replay_sizes_provenance_zip_and_typed_readback(name, tmp_path):
    """Replay/volume subsets of AC4/5/6/7, never independent scientific axes.
    @covers US-063-AC4 @covers US-063-AC5 @covers US-063-AC6
    @covers US-064-AC4 @covers US-064-AC5 @covers US-064-AC6
    @covers US-065-AC4 @covers US-065-AC5 @covers US-065-AC6
    @covers US-066-AC4 @covers US-066-AC5 @covers US-066-AC6
    @covers US-067-AC4 @covers US-067-AC5 @covers US-067-AC6
    @covers US-068-AC4 @covers US-068-AC5 @covers US-068-AC6
    @covers US-069-AC4 @covers US-069-AC5 @covers US-069-AC6
    @covers US-070-AC4 @covers US-070-AC5 @covers US-070-AC6
    @covers US-071-AC4 @covers US-071-AC5 @covers US-071-AC6
    @covers US-072-AC4 @covers US-072-AC5 @covers US-072-AC6
    @covers US-073-AC4 @covers US-073-AC5 @covers US-073-AC6
    @covers US-074-AC4 @covers US-074-AC5 @covers US-074-AC6
    @covers US-075-AC4 @covers US-075-AC5 @covers US-075-AC6
    @covers US-076-AC4 @covers US-076-AC5 @covers US-076-AC6
    """
    pack = PACKS / name / "domain-pack.json"
    template_counts = json.loads(pack.read_text())["fixture_counts"]
    for scale, components in [("small", 1), ("demo", 10), ("large", 100)]:
        data = ReplayDataset(tmp_path / f"{scale}.sqlite", pack, scale, 42)
        try:
            assert data.verified
            assert data.counts == {
                table: count * components for table, count in template_counts.items()
            }
            first, second = tmp_path / f"{scale}.zip", tmp_path / "again.zip"
            export_csv_zip(data, first)
            export_csv_zip(data, second)
            assert first.read_bytes() == second.read_bytes()
            with ZipFile(first) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                metadata = json.loads(archive.read("domain-pack.json"))
                assert manifest["origin"] == "synthetic"
                assert manifest["seed"] == 42
                assert manifest["run"]["components"] == components
                assert (
                    metadata["sources"]["scenario_replay_output"]["kind"] == "synthetic"
                )
                assert all(
                    b["source_id"] == "scenario_replay_output"
                    for b in metadata["source_bindings"]
                    if b["role"] == "rows"
                )
                for reference, member in manifest["schema_artifacts"].items():
                    assert (
                        archive.read(member) == (pack.parent / reference).read_bytes()
                    )
                assert "ontology.json" in manifest["schema_artifacts"]
                for table, spec in data.specs.items():
                    path = tmp_path / (table + ".csv")
                    path.write_bytes(archive.read(f"data/{table}.csv"))
                    decoded = list(read_csv_rows(path, spec))
                    original = [row for batch in data.batches(table) for row in batch]
                    assert decoded == original
        finally:
            data.close()
    changed = ReplayDataset(tmp_path / "different.sqlite", pack, seed=43)
    try:
        for table in changed.specs:
            first_row = next(changed.batches(table))[0]
            assert json.loads(first_row["id"])[0] == 43
    finally:
        changed.close()


def test_replay_refuses_unreviewed_profile_and_observed_templates(tmp_path):
    root = tmp_path / "pack"
    shutil.copytree(PACKS / "commerce", root)
    path = root / "domain-pack.json"
    original = json.loads(path.read_text())
    for mutation in [
        lambda p: p["execution_profile"].update(version="2.0.0"),
        lambda p: p["execution_profile"]["identity_columns"]["orders"].append("status"),
        lambda p: p["sources"]["template_orders"].update(data_kind="observed"),
        lambda p: p["execution_profile"]["scales"].update(large=10001),
    ]:
        metadata = json.loads(json.dumps(original))
        mutation(metadata)
        path.write_text(json.dumps(metadata))
        with pytest.raises(ValueError):
            ReplayDataset(tmp_path / "invalid.sqlite", path)


def test_unselected_restricted_asset_is_retained_but_not_included(tmp_path):
    root = tmp_path / "pack"
    shutil.copytree(PACKS / "construction", root)
    path = root / "domain-pack.json"
    metadata = json.loads(path.read_text())
    source = next(k for k in metadata["sources"] if k.startswith("asset_"))
    metadata["sources"][source]["license"]["redistribution"] = "unknown"
    metadata["execution_profile"]["include_sources"] = []
    path.write_text(json.dumps(metadata))
    data = ImportedDataset(tmp_path / "rows.sqlite", path)
    try:
        assert "assets/plan.svg" not in data.source_artifacts
        assert source in data.source_metadata["sources"]
    finally:
        data.close()
    metadata["execution_profile"]["include_sources"] = [source]
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="redistribution"):
        ImportedDataset(tmp_path / "refused.sqlite", path)


@pytest.mark.parametrize("name", sorted(REVIEWED))
def test_replay_preserves_component_semantics(name, tmp_path):
    """Each independent replay component retains every reviewed domain outcome."""
    from types import SimpleNamespace

    data = ReplayDataset(
        tmp_path / "replay.sqlite",
        PACKS / name / "domain-pack.json",
        scale="demo",
        seed=42,
    )
    try:
        columns = data.source_metadata["execution_profile"]["identity_columns"]
        for component in range(10):
            materialized = {}
            for table in data.specs:
                materialized[table] = []
                for batch in data.batches(table):
                    for row in batch:
                        identity = json.loads(row["id"])
                        if identity[1] != component:
                            continue
                        restored = dict(row)
                        for column in columns[table]:
                            if row[column] is not None:
                                value = json.loads(row[column])
                                assert value[:2] == [42, component], (table, column)
                                restored[column] = value[2]
                        materialized[table].append(restored)
            proxy = SimpleNamespace(
                specs=data.specs,
                source_metadata=data.source_metadata,
                batches=lambda table, rows=materialized: iter([rows[table]]),
            )
            isolated_checks(proxy, REVIEWED[name])
    finally:
        data.close()


@pytest.mark.parametrize("kind", ["schema", "source"])
def test_changed_admitted_artifact_refuses_publication(kind, tmp_path):
    packdir = tmp_path / "pack"
    shutil.copytree(PACKS / "commerce", packdir)
    data = ImportedDataset(tmp_path / "rows.sqlite", packdir / "domain-pack.json")
    try:
        artifacts = data.schema_artifacts if kind == "schema" else data.source_artifacts
        next(iter(artifacts.values())).write_text("{}")
        output = tmp_path / "output.zip"
        with pytest.raises(ValueError, match="Admitted artifact changed"):
            export_csv_zip(data, output)
        assert not output.exists()
    finally:
        data.close()
