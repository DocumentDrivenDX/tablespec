"""Legal generation properties and UC sink contract tests (no workspace)."""

from pathlib import Path
from types import SimpleNamespace

from hypothesis import given, settings, strategies as st
import pytest
from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.domains import get_domain_pack, register_domain_pack
from tablespec.sample_data.engine import SampleDataGenerator
from tablespec.sample_data.legal import LEVEL_RATES, TASKS
from tablespec.sample_data.sink import WarehouseSQLSink, load_dataset, target_namespace
from tablespec.sample_data.streaming import GeneratedDataset, plan_counts

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/legal/umf"


def dataset(tmp: Path, seed: int = 42) -> GeneratedDataset:
    config = GenerationConfig(domain="legal", random_seed=seed)
    specs = SampleDataGenerator(EXAMPLE, tmp, config).load_umf_files()
    assert len(specs) == 8
    data = GeneratedDataset(
        tmp / "rows.sqlite", specs, plan_counts(specs, "small"), config
    )
    data.generate()
    return data


@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
@settings(max_examples=12, deadline=None)
def test_deterministic_correlated_integrity(
    seed: int, tmp_path_factory: pytest.TempPathFactory
) -> None:
    left = dataset(tmp_path_factory.mktemp("left"), seed)
    right = dataset(tmp_path_factory.mktemp("right"), seed)
    try:
        assert left.report == right.report
        for table in left.specs:
            assert list(left.batches(table, 7)) == list(right.batches(table, 7))
            rows = [row for batch in left.batches(table) for row in batch]
            pk = left.specs[table]["primary_key"]
            assert len({tuple(row[c] for c in pk) for row in rows}) == len(rows)
            for fk in (
                left.specs[table].get("relationships", {}).get("foreign_keys", [])
            ):
                keys = {
                    r[fk["references_column"]]
                    for b in left.batches(fk["references_table"])
                    for r in b
                }
                assert all(row[fk["column"]] in keys for row in rows)
        matters = {r["matter_id"]: r for b in left.batches("matters") for r in b}
        people = {r["timekeeper_id"]: r for b in left.batches("timekeepers") for r in b}
        for batch in left.batches("time_entries"):
            for row in batch:
                matter = matters[row["matter_id"]]
                assert (
                    matter["open_date"]
                    <= row["entry_date"]
                    <= (
                        matter["close_date"]
                        or left.config.get_reference_date().date().isoformat()
                    )
                )
                assert (
                    row["billing_rate"]
                    == LEVEL_RATES[people[row["timekeeper_id"]]["timekeeper_level"]]
                )
                assert row["billing_narrative"].startswith(
                    TASKS[row["utbms_task_code"]]
                )
                assert ("block billed" in row["billing_narrative"]) == row[
                    "block_billed"
                ]
    finally:
        left.close()
        right.close()


class FakeSink:
    def __init__(self, fail_batch: bool = False) -> None:
        self.statements: list[str] = []
        self.fail_batch = fail_batch

    def execute(self, statement: str) -> None:
        self.statements.append(statement)
        if self.fail_batch and statement.startswith("INSERT INTO"):
            raise RuntimeError("fabricated failure")


def test_staging_batches_publication_and_cleanup(tmp_path: Path) -> None:
    data = dataset(tmp_path)
    try:
        fake = FakeSink()
        load_dataset(data, "sample.legal", fake, batch_size=3, max_statement_bytes=3000)
        assert sum(s.startswith("INSERT OVERWRITE") for s in fake.statements) == 8
        assert all(
            len(s.encode()) <= 3000
            for s in fake.statements
            if s.startswith("INSERT INTO")
        )
        assert all(
            "_tablespec_stage_" in s
            for s in fake.statements
            if s.startswith("DROP TABLE")
        )
        assert "USING DELTA" in fake.statements[1]
        before = len(fake.statements)
        load_dataset(data, "sample.legal", fake, dry_run=True)
        assert len(fake.statements) == before
        failing = FakeSink(True)
        with pytest.raises(RuntimeError, match="fabricated failure"):
            load_dataset(data, "sample.legal", failing)
        assert failing.statements[-1].startswith("DROP TABLE")
        assert not any(s.startswith("INSERT OVERWRITE") for s in failing.statements)
    finally:
        data.close()


@pytest.mark.parametrize(
    "target", ["hive_metastore.legal", "schema", "a.b.c", "a.dbfs/path", "a.b;drop"]
)
def test_target_rejections(target: str) -> None:
    with pytest.raises(ValueError):
        target_namespace(target)


def test_scale_counts_and_overrides(tmp_path: Path) -> None:
    specs = SampleDataGenerator(EXAMPLE, tmp_path, GenerationConfig()).load_umf_files()
    counts = plan_counts(specs, "demo")
    assert {
        n: counts[n]
        for n in (
            "clients",
            "matters",
            "timekeepers",
            "time_entries",
            "invoices",
            "documents",
        )
    } == dict(
        clients=25,
        matters=150,
        timekeepers=40,
        time_entries=100000,
        invoices=5000,
        documents=20000,
    )
    assert plan_counts(specs, "large")["time_entries"] == 3000000
    assert plan_counts(specs, "demo", {"clients": 2})["matters"] == 12
    assert plan_counts(specs, "demo", {"time_entries": 17})["time_entries"] == 17


def test_domain_selection_and_legacy_count() -> None:
    assert GenerationConfig(num_members=12).root_entity_count == 12
    assert GenerationConfig(root_entity_count=13).num_members == 13
    assert get_domain_pack("healthcare").registry().get_domain_type("npi")
    assert get_domain_pack("legal").registry().get_domain_type("matter_title")
    with pytest.raises(ValueError):
        get_domain_pack("missing")
    with pytest.raises(ValueError):
        register_domain_pack("legal", get_domain_pack("legal"))


def test_cli_dry_run() -> None:
    result = CliRunner().invoke(
        app,
        [
            "sample-data",
            "load",
            "--umf",
            str(EXAMPLE),
            "--target",
            "sample.legal",
            "--domain",
            "legal",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "USING DELTA" in result.output
    assert '"fk_orphan_count": 0' in result.output


def test_warehouse_polling_and_failure() -> None:
    responses = iter([SimpleNamespace(status=SimpleNamespace(state="SUCCEEDED"))])
    api = SimpleNamespace(
        execute_statement=lambda **kw: SimpleNamespace(
            statement_id="statement", status=SimpleNamespace(state="RUNNING")
        ),
        get_statement=lambda _: next(responses),
    )
    WarehouseSQLSink(
        "warehouse",
        "sample-profile",
        SimpleNamespace(statement_execution=api),
        sleep=lambda _: None,
    ).execute("SELECT 1")
    api.execute_statement = lambda **kw: SimpleNamespace(
        status=SimpleNamespace(state="FAILED")
    )
    with pytest.raises(RuntimeError, match="FAILED"):
        WarehouseSQLSink(
            "warehouse", "sample-profile", SimpleNamespace(statement_execution=api)
        ).execute("SELECT 1")


def test_unique_constraint_rejected(tmp_path: Path) -> None:
    specs = {
        "a": {
            "columns": [
                {
                    "name": "level",
                    "data_type": "STRING",
                    "domain_type": "timekeeper_level",
                }
            ],
            "primary_key": ["level"],
        }
    }
    data = GeneratedDataset(
        tmp_path / "invalid.sqlite", specs, {"a": 5}, GenerationConfig(domain="legal")
    )
    try:
        with pytest.raises(ValueError, match="Uniqueness"):
            data.generate()
    finally:
        data.close()


def test_repeated_load_replaces_and_drop_is_opt_in(tmp_path: Path) -> None:
    import re

    data = dataset(tmp_path)
    try:
        first, second = FakeSink(), FakeSink()
        load_dataset(data, "sample.legal", first)
        load_dataset(data, "sample.legal", second)

        def normalize(statements: list[str]) -> list[str]:
            return [
                re.sub(r"_tablespec_stage_[a-f0-9]+", "_tablespec_stage_owned", s)
                for s in statements
            ]

        assert normalize(first.statements) == normalize(second.statements)
        dropping = FakeSink()
        load_dataset(data, "sample.legal", dropping, drop_existing=True)
        drops = [
            s
            for s in dropping.statements
            if s.startswith("DROP TABLE") and "_tablespec_stage_" not in s
        ]
        assert len(drops) == 8
        assert all(
            s.startswith("DROP TABLE IF EXISTS `sample`.`legal`.") for s in drops
        )
    finally:
        data.close()


def test_full_comments_and_sql_parsing(tmp_path: Path) -> None:
    import sqlglot

    data = dataset(tmp_path)
    try:
        text = "Fabricated description " * 25 + " customer's clause \\ sample"
        data.specs["clients"]["description"] = text
        fake = FakeSink()
        ddls = load_dataset(data, "sample.legal", fake)
        assert text.replace("\\", "\\\\").replace("'", "\\'") in ddls[0]
        for statement in fake.statements:
            assert sqlglot.parse(statement, read="databricks")
    finally:
        data.close()


def test_warehouse_timeout_cancels() -> None:
    canceled: list[str] = []
    api = SimpleNamespace(
        execute_statement=lambda **kw: SimpleNamespace(
            statement_id="statement", status=SimpleNamespace(state="RUNNING")
        ),
        cancel_execution=canceled.append,
    )
    with pytest.raises(TimeoutError):
        WarehouseSQLSink(
            "warehouse",
            "sample-profile",
            SimpleNamespace(statement_execution=api),
            timeout_seconds=0,
        ).execute("SELECT 1")
    assert canceled == ["statement"]


def test_strict_discovery_rejects_invalid_candidate(tmp_path: Path) -> None:
    (tmp_path / "invalid.json").write_text("{}")
    with pytest.raises(ValueError):
        SampleDataGenerator(tmp_path, tmp_path, GenerationConfig()).load_umf_files(
            strict=True
        )


def test_unsupported_constraints_fail_before_sink(tmp_path: Path) -> None:
    specs = {
        "a": {
            "columns": [{"name": "id", "data_type": "INTEGER"}],
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_match_strftime_format",
                        "kwargs": {"column": "id", "strftime_format": "%Y"},
                    }
                ]
            },
        }
    }
    data = GeneratedDataset(
        tmp_path / "unsupported.sqlite", specs, {"a": 1}, GenerationConfig()
    )
    try:
        with pytest.raises(ValueError, match="Unsupported sample constraint"):
            data.generate()
        with pytest.raises(ValueError, match="verification"):
            load_dataset(data, "sample.legal", FakeSink())
    finally:
        data.close()


def test_custom_scale_configuration(tmp_path: Path) -> None:
    import yaml

    specs = SampleDataGenerator(EXAMPLE, tmp_path, GenerationConfig()).load_umf_files(
        strict=True
    )
    config_path = tmp_path / "scales.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "custom": {
                    "roots": {"clients": 2, "timekeepers": 3},
                    "children": {"matters": {"parent": "clients", "per_parent": 4}},
                }
            }
        )
    )
    counts = plan_counts(specs, "custom", preset_path=config_path)
    assert counts["matters"] == 8
    assert counts["time_entries"] == 24


@given(
    seed=st.integers(min_value=0, max_value=10000),
    count=st.integers(min_value=1, max_value=40),
)
@settings(max_examples=12, deadline=None)
def test_generic_umf_constraints(
    seed: int, count: int, tmp_path_factory: pytest.TempPathFactory
) -> None:
    specs = {
        "root": {
            "primary_key": ["id"],
            "columns": [
                {"name": "id", "data_type": "INTEGER", "nullable": False},
                {"name": "status", "data_type": "VARCHAR", "nullable": False},
                {"name": "score", "data_type": "INTEGER"},
            ],
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {"column": "status", "value_set": ["open", "closed"]},
                    },
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {
                            "column": "score",
                            "min_value": None,
                            "max_value": 10,
                        },
                    },
                    {
                        "type": "expect_column_values_to_be_of_type",
                        "kwargs": {"column": "id", "type_": "IntegerType"},
                    },
                ]
            },
        }
    }
    temp = tmp_path_factory.mktemp("generic")
    data = GeneratedDataset(
        temp / "rows.sqlite", specs, {"root": count}, GenerationConfig(random_seed=seed)
    )
    try:
        report = data.generate()
        rows = [row for batch in data.batches("root") for row in batch]
        assert len(rows) == report["root"]["row_count"] == count
        assert len({r["id"] for r in rows}) == count
        assert all(r["status"] in ("open", "closed") and r["score"] <= 10 for r in rows)
    finally:
        data.close()


def constraint_dataset(tmp_path, specs, counts):
    return GeneratedDataset(
        tmp_path / "constraints.sqlite",
        specs,
        counts,
        GenerationConfig(domain="legal", random_seed=42),
    )


def range_rule(column, minimum, maximum, **kwargs):
    return {
        "type": "expect_column_values_to_be_between",
        "kwargs": {
            "column": column,
            "min_value": minimum,
            "max_value": maximum,
            **kwargs,
        },
    }


@pytest.mark.parametrize(
    "dtype,minimum,maximum",
    [
        ("INTEGER", 1, 10),
        ("FLOAT", 1.0, 10.0),
        ("DECIMAL", 1.0, 10.0),
        ("DATE", "2024-01-01", "2024-01-10"),
    ],
)
def test_exclusive_bounds(tmp_path, dtype, minimum, maximum):
    specs = {
        "root": {
            "columns": [{"name": "value", "data_type": dtype, "scale": 2}],
            "validation_rules": {
                "expectations": [
                    range_rule(
                        "value", minimum, maximum, strict_min=True, strict_max=True
                    )
                ]
            },
        }
    }
    data = constraint_dataset(tmp_path, specs, {"root": 4})
    try:
        data.generate()
        assert all(
            minimum < row["value"] < maximum
            for batch in data.batches("root")
            for row in batch
        )
    finally:
        data.close()


@pytest.mark.parametrize("children", [10, 11])
def test_one_to_one_parent_allocation(tmp_path, children):
    specs = {
        "parent": {
            "columns": [{"name": "id", "data_type": "INTEGER"}],
            "primary_key": ["id"],
        },
        "child": {
            "columns": [
                {
                    "name": "parent_id",
                    "data_type": "INTEGER",
                    "key_type": "foreign_one_to_one",
                }
            ],
            "relationships": {
                "foreign_keys": [
                    {
                        "column": "parent_id",
                        "references_table": "parent",
                        "references_column": "id",
                    }
                ]
            },
        },
    }
    data = constraint_dataset(tmp_path, specs, {"parent": 10, "child": children})
    try:
        if children > 10:
            with pytest.raises(ValueError, match="One-to-one child count"):
                data.generate()
        else:
            data.generate()
            assert {
                row["parent_id"] for batch in data.batches("child") for row in batch
            } == set(range(1, 11))
    finally:
        data.close()


@pytest.mark.parametrize("minimum,valid", [("2024-01-05", True), ("2024-02-01", False)])
def test_entry_date_range_and_matter_period(tmp_path, minimum, valid):
    specs = {
        "matters": {
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
                {"name": "open_date", "data_type": "DATE"},
                {"name": "close_date", "data_type": "DATE"},
            ],
            "validation_rules": {
                "expectations": [
                    range_rule("open_date", "2024-01-01", "2024-01-01"),
                    range_rule("close_date", "2024-01-10", "2024-01-10"),
                ]
            },
        },
        "entries": {
            "columns": [
                {"name": "matter_id", "data_type": "INTEGER"},
                {"name": "entry_date", "data_type": "DATE"},
            ],
            "relationships": {
                "foreign_keys": [
                    {
                        "column": "matter_id",
                        "references_table": "matters",
                        "references_column": "id",
                    }
                ]
            },
            "validation_rules": {
                "expectations": [range_rule("entry_date", minimum, None)]
            },
        },
    }
    data = constraint_dataset(tmp_path, specs, {"matters": 1, "entries": 20})
    try:
        if valid:
            data.generate()
            assert all(
                minimum <= row["entry_date"] <= "2024-01-10"
                for batch in data.batches("entries")
                for row in batch
            )
        else:
            sink = FakeSink()
            with pytest.raises(ValueError, match="outside matter open period"):
                data.generate()
                load_dataset(data, "sample.legal", sink)
            assert not sink.statements
    finally:
        data.close()


@pytest.mark.parametrize("scale", ["small", "demo"])
@pytest.mark.parametrize("seed", [7, 42, 101])
def test_legal_tabular_invariants_and_distribution(tmp_path, scale, seed):
    from collections import Counter
    from decimal import Decimal

    config = GenerationConfig(domain="legal", random_seed=seed)
    specs = SampleDataGenerator(EXAMPLE, tmp_path, config).load_umf_files(strict=True)
    data = GeneratedDataset(
        tmp_path / "legal.sqlite", specs, plan_counts(specs, scale), config
    )
    try:
        data.generate()
        assert data.verification and not any(data.verification.values())
        rows = {table: [r for b in data.batches(table) for r in b] for table in specs}
        teams = {(r["matter_id"], r["timekeeper_id"]) for r in rows["matter_teams"]}
        walls = {(r["matter_id"], r["timekeeper_id"]) for r in rows["ethical_walls"]}
        assert len(teams) == len(rows["matter_teams"])
        assert len(walls) == len(rows["ethical_walls"])
        assert not teams & walls
        people = {r["timekeeper_id"]: r for r in rows["timekeepers"]}
        for matter in rows["matters"]:
            levels = {
                people[p]["timekeeper_level"]
                for m, p in teams
                if m == matter["matter_id"]
            }
            assert "partner" in levels and len(levels) >= 2
        for r in rows["time_entries"]:
            pair = r["matter_id"], r["timekeeper_id"]
            assert pair in teams and pair not in walls
            assert Decimal(str(r["amount"])) == Decimal(str(r["hours"])) * Decimal(
                str(r["billing_rate"])
            )
            assert 0.1 <= r["hours"] <= 8
        for field, parents in [
            ("matter_id", rows["matters"]),
            ("timekeeper_id", rows["timekeepers"]),
        ]:
            counter = Counter(r[field] for r in rows["time_entries"])
            counts = sorted(counter[p[field]] for p in parents)
            total, n = sum(counts), len(counts)
            gini = sum((2 * i - n - 1) * v for i, v in enumerate(counts, 1)) / (
                n * total
            )
            assert max(counts) / total < (0.5 if scale == "small" else 0.25)
            assert (0.04 if scale == "small" else 0.3) < gini < 0.85
        assert {r["client_id"] for r in rows["matters"]} == {
            r["client_id"] for r in rows["clients"]
        }
        assert (
            len({r["billing_narrative"] for r in rows["time_entries"]})
            > len(rows["time_entries"]) // 2
        )
        assert len({r["document_body"] for r in rows["documents"]}) == len(
            rows["documents"]
        )
        for r in rows["documents"]:
            if r["document_type"] != "NDA":
                assert "confidential information" not in r["document_body"]
                assert not r["nda_issues"]
            if r["nda_issues"] == "long_term":
                assert "25 years" in r["document_body"]
            if r["nda_issues"] == "residuals":
                assert "residual information" in r["document_body"]
            if r["nda_issues"] == "missing_governing_law":
                assert " govern" not in r["document_body"]
        if scale == "demo":
            ndas = [r for r in rows["documents"] if r["document_type"] == "NDA"]
            assert 0.04 < sum(bool(r["nda_issues"]) for r in ndas) / len(ndas) < 0.12
            assert {r["nda_issues"] for r in ndas} == {
                "",
                "long_term",
                "residuals",
                "missing_governing_law",
            }
        # Independent exact integer-cent reconciliation, with indexed daily aggregates.
        amounts = {}
        for r in rows["time_entries"]:
            days = amounts.setdefault(r["matter_id"], {})
            days[r["entry_date"]] = days.get(r["entry_date"], 0) + round(
                r["amount"] * 100
            )
        for invoice in rows["invoices"]:
            expected = sum(
                c
                for day, c in amounts.get(invoice["matter_id"], {}).items()
                if invoice["period_start"] <= day <= invoice["period_end"]
            )
            assert round(invoice["total_amount"] * 100) == expected
            if invoice["invoice_status"] in ("paid", "overdue"):
                assert (
                    invoice["invoice_date"]
                    <= config.get_reference_date().date().isoformat()
                )
    finally:
        data.close()


def test_bulk_upload_csv_and_cleanup(tmp_path):
    import csv
    import io
    import sqlglot
    from tablespec.sample_data.sink import bulk_stage, volume_path

    class Files:
        def __init__(self):
            self.uploads = {}
            self.deleted = []

        def upload(self, path, contents):
            self.uploads[path] = contents.read().decode()

        def delete(self, path):
            self.deleted.append(path)

    data = dataset(tmp_path)
    try:
        files, sink = Files(), FakeSink()
        bulk_stage(
            data,
            "documents",
            "`sample`.`legal`.`stage`",
            "/Volumes/sample/legal/fixtures",
            files,
            sink,
            chunk_rows=7,
        )
        assert len(files.uploads) == 6
        assert set(files.deleted) == set(files.uploads)
        csv_rows = [
            r
            for text in files.uploads.values()
            for r in csv.DictReader(io.StringIO(text))
        ]
        assert len(csv_rows) == data.counts["documents"]
        assert (
            csv_rows[0]["document_body"][1:]
            == next(data.batches("documents"))[0]["document_body"]
        )
        assert len(sink.statements) == 1 and sink.statements[0].startswith("COPY INTO")
        assert sqlglot.parse(sink.statements[0], read="databricks")
        failing = FakeSink()
        failing.execute = lambda _: (_ for _ in ()).throw(RuntimeError("copy failure"))
        files = Files()
        with pytest.raises(RuntimeError, match="copy failure"):
            bulk_stage(
                data,
                "documents",
                "`sample`.`legal`.`stage`",
                "/Volumes/sample/legal/fixtures",
                files,
                failing,
            )
        assert set(files.deleted) == set(files.uploads)
        for invalid in ("dbfs:/tmp", "/Volumes/a/b", "/Volumes/a/b/c/../x"):
            with pytest.raises(ValueError):
                volume_path(invalid)
    finally:
        data.close()


def test_readback_checks_detect_loaded_corruption(tmp_path):
    from tablespec.sample_data.verification import verify_loaded
    import re

    data = dataset(tmp_path)

    class Readback:
        def query(self, statement):
            local = re.sub(r"`sample`.`legal`.(`\w+`)", r"\1", statement)
            return [list(row) for row in data.db.execute(local)]

    try:
        result = verify_loaded(
            data.specs, data.counts, "sample.legal", Readback(), legal=True
        )
        assert all(r["passed"] for r in result.values())
        data.db.execute(
            "UPDATE rows SET body=json_set(body,'$.timekeeper_id',9999) WHERE tbl='time_entries' AND idx=0"
        )
        with pytest.raises(RuntimeError, match="FAILED"):
            verify_loaded(
                data.specs, data.counts, "sample.legal", Readback(), legal=True
            )
    finally:
        data.close()


def test_spark_and_warehouse_readback_adapters():
    from tablespec.sample_data.sink import SparkSQLSink

    spark = SimpleNamespace(sql=lambda _: SimpleNamespace(collect=lambda: [(12,)]))
    assert SparkSQLSink(spark).query("SELECT COUNT(*)") == [[12]]
    api = SimpleNamespace(
        execute_statement=lambda **kw: SimpleNamespace(
            status=SimpleNamespace(state="SUCCEEDED"),
            result=SimpleNamespace(data_array=[["12"]]),
        )
    )
    assert WarehouseSQLSink(
        "warehouse", "sample-profile", SimpleNamespace(statement_execution=api)
    ).query("SELECT COUNT(*)") == [["12"]]


def test_verify_only_cli_does_not_generate_or_write(tmp_path, monkeypatch):
    import re
    from tablespec.sample_data import load_cli

    data = dataset(tmp_path)

    class ReadbackWarehouse:
        def __init__(self, *args):
            pass

        def query(self, statement):
            return [
                list(row)
                for row in data.db.execute(
                    re.sub(r"`sample`.`legal`.(`\w+`)", r"\1", statement)
                )
            ]

        def execute(self, statement):
            raise AssertionError("verify-only must not write")

    try:
        monkeypatch.setattr(load_cli, "WarehouseSQLSink", ReadbackWarehouse)
        monkeypatch.setattr(
            GeneratedDataset,
            "generate",
            lambda _: (_ for _ in ()).throw(AssertionError("must not generate")),
        )
        result = CliRunner().invoke(
            app,
            [
                "sample-data",
                "load",
                "--umf",
                str(EXAMPLE),
                "--target",
                "sample.legal",
                "--domain",
                "legal",
                "--verify-only",
                "--warehouse-id",
                "warehouse",
                "--profile",
                "sample-profile",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Load verification PASSED" in result.output
    finally:
        data.close()


def test_sdk_volume_files_port():
    import io
    from tablespec.sample_data.sink import SDKVolumeFiles

    calls = []
    client = SimpleNamespace(
        files=SimpleNamespace(
            create_directory=lambda path: calls.append(("mkdir", path)),
            upload=lambda path, contents, **kw: calls.append(
                ("upload", path, contents.read(), kw)
            ),
            delete=lambda path: calls.append(("delete", path)),
        )
    )
    port = SDKVolumeFiles(client)
    path = "/Volumes/sample/legal/fixtures/owned/part.csv"
    port.upload(path, io.BytesIO(b"synthetic rows"))
    port.delete(path)
    assert calls == [
        ("mkdir", path.rsplit("/", 1)[0]),
        ("upload", path, b"synthetic rows", {"overwrite": False}),
        ("delete", path),
    ]


def test_bulk_publication_and_failure_cleanup(tmp_path):
    from tablespec.sample_data.sink import load_dataset

    class Files:
        def __init__(self):
            self.paths = []
            self.deleted = []

        def upload(self, path, contents):
            assert contents.read(1)
            self.paths.append(path)

        def delete(self, path):
            self.deleted.append(path)

    data = dataset(tmp_path)
    try:
        sink, files = FakeSink(), Files()
        load_dataset(
            data,
            "sample.legal",
            sink,
            volume="/Volumes/sample/legal/fixtures",
            files=files,
        )
        assert sum(s.startswith("COPY INTO") for s in sink.statements) == 8
        assert sum(s.startswith("INSERT OVERWRITE") for s in sink.statements) == 8
        assert not any(s.startswith("INSERT INTO") for s in sink.statements)
        assert set(files.paths) == set(files.deleted)

        class FailingCopy(FakeSink):
            def execute(self, statement):
                super().execute(statement)
                if statement.startswith("COPY INTO"):
                    raise RuntimeError("synthetic copy failure")

        sink, files = FailingCopy(), Files()
        with pytest.raises(RuntimeError, match="copy failure"):
            load_dataset(
                data,
                "sample.legal",
                sink,
                volume="/Volumes/sample/legal/fixtures",
                files=files,
            )
        assert sink.statements[-1].startswith("DROP TABLE IF EXISTS")
        assert not any(s.startswith("INSERT OVERWRITE") for s in sink.statements)
        assert set(files.paths) == set(files.deleted)
    finally:
        data.close()
