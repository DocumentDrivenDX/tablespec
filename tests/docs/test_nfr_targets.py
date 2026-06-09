"""Regression coverage for measurable HELIX NFR targets."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def _normalized_docs() -> str:
    docs = "\n".join(
        [
            _read("docs/helix/01-frame/features/FEAT-024-native-spark-profiler.md"),
            _read(
                "docs/helix/01-frame/features/FEAT-025-connect-safe-gx-validation.md"
            ),
            _read(
                "docs/helix/01-frame/features/FEAT-026-compile-orchestrator-bootstrap.md"
            ),
            _read("docs/helix/01-frame/features/FEAT-027-dbt-emitter.md"),
            _read("docs/helix/01-frame/features/FEAT-028-ldp-sibling-emitter.md"),
        ]
    )
    return " ".join(docs.split())


def test_prd_success_metrics_are_measurable() -> None:
    prd = _read("docs/helix/01-frame/prd.md")

    assert "0 byte diffs for unchanged UMF inputs" in prd
    assert "100% of required artifact seams emitted" in prd
    assert "Byte-identical canonical rows" in prd
    assert "0 tablespec generation imports" in prd
    assert "At least 50% lower transform/validation authoring time" in prd


def test_feature_nfrs_name_numeric_targets_and_evidence() -> None:
    docs = _normalized_docs()

    expected_fragments = [
        "byte-identical `DataFrameProfile` / `key_candidates`",
        "O(columns) profiling jobs",
        "zero divergence between classic Spark and Spark Connect",
        "100% of per-expectation execution errors",
        "0 byte diffs across committed artifacts",
        "100% of per-table manifest entries",
        "0 byte diffs in project files",
        "matches 100% of the corresponding GX baseline constraint set",
        "0 Databricks or Spark runtime packages",
        "0 byte diffs in LDP SQL",
    ]

    for fragment in expected_fragments:
        assert fragment in docs


def test_nfr_evidence_commands_are_recorded() -> None:
    docs = _normalized_docs()

    for command in [
        "uv run pytest tests/unit/test_profiler_connect_sail.py",
        "uv run pytest tests/unit/test_validation_connect_sail.py",
        "uv run pytest tests/e2e/test_bootstrap_from_specs.py",
        "uv run pytest tests/dbt_dag tests/conformance",
        "uv run pytest tests/ldp tests/conformance/test_ldp_tiers.py",
    ]:
        assert command in docs


def test_connect_validation_docs_describe_fail_closed_unsupported_expectations() -> (
    None
):
    docs = (
        _normalized_docs()
        + " "
        + " ".join(
            _read(
                "docs/helix/01-frame/user-stories/US-022-validate-suite-on-connect-without-silent-failure.md"
            ).split()
        )
    )

    assert "unsupported expectations fail closed" in docs
    assert "unsupported-passing stub" not in docs
    assert "surfaced as a passing result" not in docs


def test_validation_pipeline_docs_no_stale_profile_mapper_todo() -> None:
    text = _read("docs/helix/01-frame/features/FEAT-017-validation-pipeline.md")

    assert "TODO stub" not in text
    assert "ProfileToGxMapper" in text
    assert "src/tablespec/profiling/gx_expectation_builder.py" in text
