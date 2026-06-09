"""Key-candidate sidecar contract for bootstrap/compile artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml

from tablespec.e2e.compile import compile_umfs
from tablespec.e2e.manifest import CompiledArtifacts
from tablespec.profiling import KeyCandidate, KeyCandidateEvidence
from tests.builders import UMFBuilder


def _umf():
    return (
        UMFBuilder("member")
        .column("id", "INTEGER", nullable=False)
        .column("event_date", "VARCHAR", nullable=False)
        .column("name", "VARCHAR", nullable=True)
        .build()
    )


def _candidate(
    columns: list[str],
    *,
    score: float,
    kind: str = "primary_key_candidate",
    minimal: bool = True,
    nullable: bool = False,
) -> dict:
    return asdict(
        KeyCandidate(
            columns=columns,
            kind=kind,  # type: ignore[arg-type]
            verified_exact=True,
            exact_unique=True,
            emitted=True,
            evidence=KeyCandidateEvidence(
                row_count=3,
                columns=columns,
                null_count_by_column={column: 0 for column in columns},
                exact_distinct_count=3,
                approximate_distinct_count_by_column={column: 3 for column in columns},
                distinct_ratio=1.0,
                completeness_by_column={column: 1.0 for column in columns},
                verified_exact=True,
                nullable=nullable,
                minimal=minimal,
                subset_unique=False,
                score=score,
                score_components={"distinct_ratio": 1.0},
                name_hints=["id"] if columns == ["id"] else [],
                type_hints=[],
                penalties=[],
                verification_pass_count=1,
                verification_query_count=1,
                reason="test candidate",
            ),
        )
    )


def _compile(
    out: Path,
    *,
    infer_keys: str,
    candidates: list[dict] | None = None,
    key_promotion_min_gap: float = 0.05,
) -> CompiledArtifacts:
    return compile_umfs(
        [_umf()],
        out,
        source="tables",
        infer_keys=infer_keys,
        key_candidates={"member": candidates or []},
        key_promotion_min_gap=key_promotion_min_gap,
    )


def _sidecar(artifacts: CompiledArtifacts) -> dict:
    path = artifacts.table("member").key_candidates_json
    assert path is not None
    return json.loads(path.read_text())


def _snapshot(artifacts: CompiledArtifacts) -> dict:
    return yaml.safe_load(artifacts.table("member").umf_snapshot.read_text())


def test_bootstrap_candidates_write_sidecar_without_umf_mutation(
    tmp_path: Path,
) -> None:
    artifacts = _compile(
        tmp_path,
        infer_keys="candidates",
        candidates=[_candidate(["id"], score=0.95)],
    )

    sidecar_path = artifacts.table("member").key_candidates_json
    assert sidecar_path is not None
    assert sidecar_path.exists()
    assert sidecar_path.relative_to(artifacts.root).as_posix() == (
        "validation/member.keycandidates.json"
    )

    manifest = json.loads(artifacts.manifest_path.read_text())
    assert manifest["tables"]["member"]["key_candidates_json"] == (
        "validation/member.keycandidates.json"
    )
    reloaded = CompiledArtifacts.load(tmp_path)
    assert reloaded.table("member").key_candidates_json == sidecar_path

    snapshot = _snapshot(artifacts)
    assert "primary_key" not in snapshot
    assert "unique_constraints" not in snapshot


def test_keycandidate_sidecar_json_schema(tmp_path: Path) -> None:
    artifacts = _compile(
        tmp_path,
        infer_keys="candidates",
        candidates=[_candidate(["id"], score=0.95)],
    )

    sidecar = _sidecar(artifacts)
    evidence = sidecar["candidates"][0]["evidence"]

    assert sidecar["table_name"] == "member"
    assert sidecar["mode"] == "candidates"
    assert sidecar["promotion"]["promoted"] is False
    assert [candidate["columns"] for candidate in sidecar["candidates"]] == [["id"]]
    assert set(evidence) == {
        "row_count",
        "columns",
        "null_count_by_column",
        "exact_distinct_count",
        "approximate_distinct_count_by_column",
        "distinct_ratio",
        "completeness_by_column",
        "verified_exact",
        "nullable",
        "minimal",
        "subset_unique",
        "score",
        "score_components",
        "name_hints",
        "type_hints",
        "penalties",
        "verification_pass_count",
        "verification_query_count",
        "reason",
    }


def test_bootstrap_auto_conflict_does_not_promote(tmp_path: Path) -> None:
    artifacts = _compile(
        tmp_path,
        infer_keys="auto",
        key_promotion_min_gap=0.1,
        candidates=[
            _candidate(["id"], score=0.95),
            _candidate(["event_date"], score=0.91),
        ],
    )

    sidecar = _sidecar(artifacts)

    assert sidecar["promotion"]["promoted"] is False
    assert "score gap" in sidecar["promotion"]["reason"]
    assert "primary_key" not in _snapshot(artifacts)


def test_bootstrap_auto_single_clear_key_promotes_with_metadata(
    tmp_path: Path,
) -> None:
    artifacts = _compile(
        tmp_path,
        infer_keys="auto",
        candidates=[_candidate(["id"], score=0.95)],
    )

    sidecar = _sidecar(artifacts)
    snapshot = _snapshot(artifacts)

    assert snapshot["primary_key"] == ["id"]
    assert sidecar["promotion"]["promoted"] is True
    assert sidecar["promotion"]["columns"] == ["id"]
    assert (
        "dbt incremental MERGE unique_key may change"
        in sidecar["promotion"]["downstream_effects"]
    )


def test_candidate_sidecar_deterministic_across_runs(tmp_path: Path) -> None:
    candidates = [
        _candidate(["event_date"], score=0.8),
        _candidate(["id"], score=0.95),
    ]

    first = _compile(tmp_path / "first", infer_keys="candidates", candidates=candidates)
    second = _compile(
        tmp_path / "second",
        infer_keys="candidates",
        candidates=list(reversed(candidates)),
    )

    assert first.table("member").key_candidates_json is not None
    assert second.table("member").key_candidates_json is not None
    assert (
        first.table("member").key_candidates_json.read_text()
        == second.table("member").key_candidates_json.read_text()
    )


def test_candidate_mode_does_not_change_generated_runtime_artifacts(
    tmp_path: Path,
) -> None:
    none_artifacts = _compile(tmp_path / "none", infer_keys="none")
    candidate_artifacts = _compile(
        tmp_path / "candidates",
        infer_keys="candidates",
        candidates=[_candidate(["id"], score=0.95)],
    )

    none_member = none_artifacts.table("member")
    candidate_member = candidate_artifacts.table("member")

    for attr in (
        "umf_snapshot",
        "ingest_sql",
        "ddl_sql",
        "pyspark_schema",
        "json_schema",
        "suite_json",
    ):
        assert (
            getattr(none_member, attr).read_text()
            == getattr(candidate_member, attr).read_text()
        )

    assert none_member.key_candidates_json is None
    assert candidate_member.key_candidates_json is not None
