"""Mixed legal source fidelity and private processing boundaries."""

import csv
from pathlib import Path
import shutil

import pytest
from typer.testing import CliRunner

from tablespec.sample_data.archive import export_csv_zip
from tablespec.sample_data.load_cli import app
from tablespec.sample_data.mixed import MixedDataset

PACK = (
    Path(__file__).resolve().parents[2] / "examples/domain-packs/legal/domain-pack.json"
)


def test_mixed_legal_preserves_fixed_evidence_and_exact_text(tmp_path):
    data = MixedDataset(tmp_path / "rows.sqlite", PACK, source_policy="local-use")
    try:
        assert data.verified
        assert len(data.specs) == 11
        assert "ontology.json" in data.schema_artifacts
        assert data.counts["cases"] == 1
        assert data.counts["evidence_documents"] == 7
        assert data.counts["evidence_pages"] == 383
        with (PACK.parent / "data/evidence_pages.csv").open(newline="") as stream:
            original = list(csv.DictReader(stream))
        imported = [row for batch in data.batches("evidence_pages") for row in batch]
        assert [(r["page_key"], r["text"]) for r in imported] == [
            (r["page_key"], r["text"]) for r in original
        ]
        assert all("matter_id" not in r for r in imported)
        assert data.run_metadata["origin"] == "mixed"
        assert (
            data.source_metadata["sources"]["PTX0032"]["license"]["redistribution"]
            == "unknown"
        )
        with pytest.raises(ValueError, match="redistribution"):
            export_csv_zip(data, tmp_path / "uncleared.zip")
        assert not (tmp_path / "uncleared.zip").exists()
    finally:
        data.close()


def test_mixed_seed_changes_synthetic_rows_without_changing_evidence(tmp_path):
    first = MixedDataset(
        tmp_path / "first.sqlite", PACK, seed=7, source_policy="local-use"
    )
    second = MixedDataset(
        tmp_path / "second.sqlite", PACK, seed=101, source_policy="local-use"
    )
    try:
        assert list(first.batches("evidence_pages")) == list(
            second.batches("evidence_pages")
        )
        assert list(first.batches("clients")) != list(second.batches("clients"))
    finally:
        first.close()
        second.close()


def test_unknown_rights_and_tampered_originals_refuse_before_target_writes(tmp_path):
    with pytest.raises(ValueError, match="redistribution"):
        MixedDataset(tmp_path / "denied.sqlite", PACK)
    assert not (tmp_path / "denied.sqlite").exists()
    root = tmp_path / "pack"
    shutil.copytree(PACK.parent, root)
    (root / "sources/PTX0032.pdf").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        MixedDataset(
            tmp_path / "bad.sqlite",
            root / "domain-pack.json",
            source_policy="local-use",
        )
    assert not (tmp_path / "bad.sqlite").exists()


def test_mixed_cli_prepares_all_tables_without_workspace_authentication(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "--mixed",
            "--pack",
            str(PACK),
            "--source-policy",
            "local-use",
            "--target",
            "samples.legal_mixed",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "evidence_pages" in result.output
    assert "CREATE TABLE" in result.output
    denied = CliRunner().invoke(
        app,
        [
            "ingest",
            "--mixed",
            "--pack",
            str(PACK),
            "--source-policy",
            "local-use",
            "--output",
            str(tmp_path / "denied.zip"),
        ],
    )
    assert denied.exit_code == 1
    assert not (tmp_path / "denied.zip").exists()


def test_databricks_notebook_preflight_uses_no_spark_or_workspace_writes(
    monkeypatch, capsys
):
    import runpy
    from types import SimpleNamespace
    import tablespec.spark_factory

    class Widgets:
        values = {
            "pack_path": str(PACK),
            "target": "samples.legal_mixed",
            "load_tables": "false",
        }

        def text(self, name, default):
            self.values.setdefault(name, default)

        def dropdown(self, name, default, options):
            self.values.setdefault(name, default)

        def get(self, name):
            return self.values[name]

    def unexpected_spark(*args, **kwargs):
        raise AssertionError("Preflight must not access a Spark session")

    monkeypatch.setattr(
        tablespec.spark_factory, "create_delta_spark_session", unexpected_spark
    )
    runpy.run_path(
        str(PACK.parents[3] / "scripts/load_mixed_legal_databricks.py"),
        init_globals={"dbutils": SimpleNamespace(widgets=Widgets())},
    )
    output = capsys.readouterr().out
    assert "Preflight PASSED" in output
    assert '"evidence_pages": 383' in output
