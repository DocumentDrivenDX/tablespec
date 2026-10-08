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
                assert matter["open_date"] <= row["entry_date"] <= matter["close_date"]
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
