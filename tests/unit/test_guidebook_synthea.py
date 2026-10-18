"""Guidebook + lineage smoke test against the committed Synthea example."""

# @covers US-046-AC5

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tablespec.cli import app
from tablespec.lineage import DiscoveredUMFProvider, LineageBuilder

UMFS = Path(__file__).resolve().parents[2] / "examples" / "synthea" / "umfs"


def test_member_quality_summary_traces_to_ingested_tables():
    graph = LineageBuilder(DiscoveredUMFProvider(UMFS)).trace_table(
        "", "member_quality_summary"
    )

    assert graph.warnings == []
    # Base table matches the SQL plan generator's hub/fallback inference.
    assert graph.tables["member_quality_summary"].base_table == "conditions"
    leaves = {
        target.rsplit(".", 1)[1]: {leaf.column_id for leaf in summary}
        for target, summary in graph.leaf_summaries.items()
    }
    assert leaves["patient_id"] == {"patients.Id"}
    assert leaves["pcp_name"] == {"providers.NAME"}
    assert leaves["latest_a1c"] == {"observations.VALUE"}
    assert all(
        graph.tables[leaf.table_id].table_type == "ingested"
        for summary in graph.leaf_summaries.values()
        for leaf in summary
    )


def test_cli_lineage_text_and_json():
    runner = CliRunner()
    text = runner.invoke(
        app, ["lineage", str(UMFS), "member_quality_summary", "-c", "pcp_name"]
    )
    assert text.exit_code == 0, text.output
    assert "providers.NAME" in text.output

    as_json = runner.invoke(
        app,
        [
            "lineage",
            str(UMFS),
            "member_quality_summary",
            "-c",
            "pcp_name",
            "-f",
            "json",
        ],
    )
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.output)["targets"] == ["member_quality_summary.pcp_name"]


def test_cli_lineage_html_writes_single_file(tmp_path: Path):
    out = tmp_path / "mqs.html"
    result = CliRunner().invoke(
        app,
        ["lineage", str(UMFS), "member_quality_summary", "-f", "html", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    html = out.read_text(encoding="utf-8")
    assert 'id="page-data"' in html
    assert "<script src=" not in html


def test_cli_lineage_errors():
    runner = CliRunner()
    missing = runner.invoke(app, ["lineage", str(UMFS), "nope"])
    assert missing.exit_code == 1
    assert "Table not found" in missing.output
    bad_format = runner.invoke(app, ["lineage", str(UMFS), "claims", "-f", "xml"])
    assert bad_format.exit_code == 1
