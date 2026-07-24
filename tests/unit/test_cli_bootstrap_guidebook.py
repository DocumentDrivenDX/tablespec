"""CLI acceptance for bootstrap (Path B) and guidebook empty-input UX."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tablespec.cli import app

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})

FIXTURE = Path(__file__).resolve().parents[1] / "e2e" / "fixtures" / "member.umf.yaml"


def test_bootstrap_compiles_spec_to_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    result = runner.invoke(
        app,
        ["bootstrap", str(FIXTURE), "-o", str(out), "--dialect", "duckdb"],
    )
    assert result.exit_code == 0, result.output
    assert "Compiled" in result.output
    assert out.exists()
    # Manifest / table artifacts present
    assert any(out.rglob("*.sql")) or any(out.rglob("*.json"))


def test_bootstrap_missing_path_fails() -> None:
    result = runner.invoke(
        app,
        ["bootstrap", "/no/such/umf", "-o", "/tmp/out"],
    )
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_guidebook_missing_root_fails() -> None:
    result = runner.invoke(app, ["guidebook", "/no/such/dir", "-o", "/tmp/gb"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_guidebook_empty_dir_fails(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "gb"
    result = runner.invoke(app, ["guidebook", str(empty), "-o", str(out)])
    assert result.exit_code == 1
    assert "No UMFs found" in result.output
