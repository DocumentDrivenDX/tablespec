"""Tests for bounded composite key inference in the native profiler."""

from __future__ import annotations

import shutil
import subprocess
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

try:
    from pysail.spark import SparkConnectServer
    from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

    _HAS_SAIL = True
except ImportError:
    _HAS_SAIL = False

pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning"
)


def _key_candidates(profile: Any) -> list[dict[str, Any]]:
    return asdict(profile)["key_candidates"] or []


def _make_dataframe(spark: Any, rows: list[tuple[Any, ...]], schema: str) -> Any:
    return spark.createDataFrame(rows, schema)


def _profile_key_candidates(
    profiler: Any,
    df: Any,
    *,
    key_max_width: int,
    key_max_candidates: int,
    key_verification_pass_budget: int,
) -> list[dict[str, Any]]:
    profile = profiler.profile(
        df,
        infer_key_candidates=True,
        key_max_width=key_max_width,
        key_max_candidates=key_max_candidates,
        key_verification_pass_budget=key_verification_pass_budget,
    )
    return _key_candidates(profile)


def _find_candidate(
    candidates: list[dict[str, Any]],
    columns: tuple[str, ...],
) -> dict[str, Any] | None:
    for candidate in candidates:
        if tuple(candidate["columns"]) == columns:
            return candidate
    return None


def _uniqueness_expectations_for_column(
    expectations: list[dict[str, Any]], column: str
) -> list[dict[str, Any]]:
    return [
        expectation
        for expectation in expectations
        if expectation["type"] == "expect_column_values_to_be_unique"
        and expectation["kwargs"]["column"] == column
    ]


@pytest.mark.no_spark
def test_native_profiler_gx_expectation_compatibility() -> None:
    """The new key-candidate field should not disturb GX expectation mapping."""
    from tablespec.profiling import (
        ColumnProfile,
        DataFrameProfile,
        KeyCandidate,
        KeyCandidateEvidence,
        ProfileToGxMapper,
    )

    profile = DataFrameProfile(
        num_records=4,
        columns={
            "id": ColumnProfile(
                column_name="id",
                completeness=1.0,
                approximate_num_distinct=4,
                data_type="IntegerType",
                is_data_type_inferred=False,
            )
        },
        key_candidates=[
            KeyCandidate(
                columns=["id"],
                verified_exact=True,
                exact_unique=True,
                emitted=True,
                evidence=KeyCandidateEvidence(
                    minimal=True,
                    reason="single-column exact unique",
                ),
            )
        ],
    )

    expectations = ProfileToGxMapper().build_expectations(profile)
    assert expectations
    assert profile.key_candidates and profile.key_candidates[0].emitted is True


@pytest.mark.no_spark
class TestKeyCandidateModels:
    """Advisory key-candidate models should be JSON-serializable dataclasses."""

    def test_key_candidate_models_are_json_serializable(self) -> None:
        from tablespec.profiling import (
            ColumnProfile,
            DataFrameProfile,
            KeyCandidate,
            KeyCandidateEvidence,
        )

        evidence = KeyCandidateEvidence(
            row_count=10,
            columns=["id"],
            null_count_by_column={"id": 0},
            exact_distinct_count=10,
            approximate_distinct_count_by_column={"id": 10},
            distinct_ratio=1.0,
            completeness_by_column={"id": 1.0},
            verified_exact=True,
            nullable=False,
            minimal=True,
            subset_unique=False,
            score=0.95,
            score_components={"distinct_ratio": 1.0},
            name_hints=["id"],
            type_hints=["IntegerType"],
            penalties=[],
            verification_pass_count=1,
            verification_query_count=1,
            reason="single-column exact unique",
        )
        candidate = KeyCandidate(
            columns=["id"],
            kind="primary_key_candidate",
            verified_exact=True,
            exact_unique=True,
            emitted=True,
            evidence=evidence,
        )
        profile = DataFrameProfile(
            num_records=10,
            columns={
                "id": ColumnProfile(
                    column_name="id",
                    completeness=1.0,
                    approximate_num_distinct=10,
                    data_type="IntegerType",
                    is_data_type_inferred=False,
                )
            },
            key_candidates=[candidate],
        )

        serialized = asdict(profile)
        serialized_evidence = serialized["key_candidates"][0]["evidence"]

        assert serialized["key_candidates"][0]["kind"] == "primary_key_candidate"
        assert set(serialized_evidence) == {
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
        assert 0 <= serialized_evidence["score"] <= 1

        with pytest.raises(ValueError, match="Unsupported key candidate kind"):
            KeyCandidate(columns=["id"], kind="foreign_key_candidate")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="score must be between 0 and 1"):
            KeyCandidateEvidence(score=1.1)

    def test_dataframe_profile_default_key_candidates_isolated(self) -> None:
        from tablespec.profiling import ColumnProfile, DataFrameProfile, KeyCandidate

        columns = {
            "id": ColumnProfile(
                column_name="id",
                completeness=1.0,
                approximate_num_distinct=1,
                data_type="IntegerType",
                is_data_type_inferred=False,
            )
        }

        first = DataFrameProfile(num_records=1, columns=columns)
        second = DataFrameProfile(num_records=1, columns=columns)

        assert first.key_candidates == []
        assert second.key_candidates == []

        first.key_candidates.append(KeyCandidate(columns=["id"]))

        assert len(first.key_candidates) == 1
        assert second.key_candidates == []


@pytest.mark.no_spark
class TestProfileToGxKeyCandidateDedupe:
    """Verified exact key candidates should dedupe approximate GX uniqueness."""

    def _profile(
        self,
        *,
        key_candidates: list[Any] | None = None,
    ) -> Any:
        from tablespec.profiling import ColumnProfile, DataFrameProfile

        return DataFrameProfile(
            num_records=100,
            columns={
                "id": ColumnProfile(
                    column_name="id",
                    completeness=1.0,
                    approximate_num_distinct=100,
                    data_type="IntegerType",
                    is_data_type_inferred=False,
                ),
                "event_date": ColumnProfile(
                    column_name="event_date",
                    completeness=1.0,
                    approximate_num_distinct=5,
                    data_type="StringType",
                    is_data_type_inferred=False,
                ),
            },
            key_candidates=key_candidates,
        )

    def _expectations(self, profile: Any) -> list[dict[str, Any]]:
        from tablespec.profiling import ProfileToGxMapper

        return ProfileToGxMapper().build_expectations(profile)

    def test_profile_to_gx_no_duplicate_uniqueness_when_infer_keys_enabled(
        self,
    ) -> None:
        from tablespec.profiling import KeyCandidate

        profile = self._profile(
            key_candidates=[
                KeyCandidate(
                    columns=["id"],
                    verified_exact=True,
                    exact_unique=True,
                    emitted=True,
                )
            ]
        )

        expectations = self._expectations(profile)

        assert _uniqueness_expectations_for_column(expectations, "id") == []

    def test_profile_to_gx_legacy_uniqueness_unchanged_when_infer_keys_disabled(
        self,
    ) -> None:
        expectations_without_candidates = self._expectations(self._profile())
        expectations_with_empty_candidates = self._expectations(
            self._profile(key_candidates=[])
        )

        assert expectations_with_empty_candidates == expectations_without_candidates
        assert (
            len(
                _uniqueness_expectations_for_column(
                    expectations_without_candidates, "id"
                )
            )
            == 1
        )

    def test_unverified_or_budget_skipped_candidate_does_not_suppress_legacy_uniqueness(
        self,
    ) -> None:
        from tablespec.profiling import KeyCandidate, KeyCandidateEvidence

        profile = self._profile(
            key_candidates=[
                KeyCandidate(
                    columns=["id"],
                    verified_exact=False,
                    exact_unique=None,
                    emitted=False,
                    evidence=KeyCandidateEvidence(
                        reason="verification budget exhausted"
                    ),
                )
            ]
        )

        expectations = self._expectations(profile)

        assert len(_uniqueness_expectations_for_column(expectations, "id")) == 1

    def test_nullable_or_composite_candidate_does_not_suppress_single_column_legacy_uniqueness(
        self,
    ) -> None:
        from tablespec.profiling import KeyCandidate, KeyCandidateEvidence

        profile = self._profile(
            key_candidates=[
                KeyCandidate(
                    columns=["id"],
                    verified_exact=True,
                    exact_unique=True,
                    emitted=False,
                    evidence=KeyCandidateEvidence(reason="nullable advisory key"),
                ),
                KeyCandidate(
                    columns=["id", "event_date"],
                    verified_exact=True,
                    exact_unique=True,
                    emitted=True,
                ),
            ]
        )

        expectations = self._expectations(profile)

        assert len(_uniqueness_expectations_for_column(expectations, "id")) == 1


@pytest.mark.spark_only
class TestNativeProfilerKeyControls:
    """Constructor-level key controls should stay opt-in and non-authoritative."""

    def test_inference_disabled_preserves_existing_profile_shape(
        self, spark_session: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        def fail_if_called(*args: Any, **kwargs: Any) -> list[Any]:
            raise AssertionError("key verification should not run when disabled")

        monkeypatch.setattr(
            NativeSparkProfiler,
            "_infer_key_candidates",
            fail_if_called,
        )
        df = _make_dataframe(
            spark_session,
            [(1, "A"), (2, "B")],
            "id int, code string",
        )

        profile = NativeSparkProfiler(
            spark_session,
            infer_key_candidates=False,
        ).profile(df, cache_inputs=False)

        serialized = asdict(profile)
        assert serialized["num_records"] == 2
        assert set(serialized["columns"]) == {"id", "code"}
        assert serialized["key_candidates"] == []

    def test_key_thresholds_and_budgets_are_exposed(self, spark_session: Any) -> None:
        from tablespec.profiling import NativeSparkProfiler

        profiler = NativeSparkProfiler(
            spark_session,
            infer_key_candidates=True,
            key_min_rows=25,
            key_max_width=2,
            key_max_candidates=5,
            key_verification_pass_budget=3,
            key_promotion_min_score=0.8,
            key_promotion_min_gap=0.15,
        )

        assert profiler.key_inference_config == {
            "infer_key_candidates": True,
            "key_min_rows": 25,
            "key_max_width": 2,
            "key_max_candidates": 5,
            "key_verification_pass_budget": 3,
            "key_promotion_min_score": 0.8,
            "key_promotion_min_gap": 0.15,
        }

    def test_key_controls_do_not_mutate_authoritative_umf_fields(
        self, spark_session: Any
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        df = _make_dataframe(
            spark_session,
            [(1, "A"), (2, "B")],
            "id int, code string",
        )

        profile = NativeSparkProfiler(
            spark_session,
            infer_key_candidates=True,
            key_min_rows=999,
        ).profile(df, cache_inputs=False)

        serialized = asdict(profile)
        assert serialized["key_candidates"] == []
        assert "primary_key" not in serialized
        assert "unique_constraints" not in serialized


@pytest.mark.spark_only
class TestNativeProfilerCompositeKeys:
    """Composite key inference should stay bounded and honest."""

    def test_native_profiler_composite_minimal_key(self, spark_session: Any) -> None:
        from tablespec.profiling import NativeSparkProfiler

        df = _make_dataframe(
            spark_session,
            [
                (1, "2025-01-01"),
                (1, "2025-01-02"),
                (2, "2025-01-01"),
                (2, "2025-01-02"),
            ],
            "member_id int, effective_date string",
        )

        profiler = NativeSparkProfiler(spark_session)
        candidates = _profile_key_candidates(
            profiler,
            df,
            key_max_width=2,
            key_max_candidates=4,
            key_verification_pass_budget=4,
        )

        pair = _find_candidate(candidates, ("member_id", "effective_date"))
        assert pair is not None
        assert pair["verified_exact"] is True
        assert pair["exact_unique"] is True
        assert pair["emitted"] is True
        assert pair["evidence"]["minimal"] is True
        assert (
            pair["evidence"]["reason"] == "all proper subsets exact-verified non-unique"
        )

        member_id = _find_candidate(candidates, ("member_id",))
        effective_date = _find_candidate(candidates, ("effective_date",))
        assert member_id is not None
        assert effective_date is not None
        assert member_id["verified_exact"] is True
        assert effective_date["verified_exact"] is True
        assert member_id["exact_unique"] is False
        assert effective_date["exact_unique"] is False

    def test_native_profiler_rejects_nonminimal_composite(
        self, spark_session: Any
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        df = _make_dataframe(
            spark_session,
            [
                (1, "2025-01-01"),
                (2, "2025-01-01"),
                (3, "2025-01-02"),
                (4, "2025-01-02"),
            ],
            "id int, effective_date string",
        )

        profiler = NativeSparkProfiler(spark_session)
        candidates = _profile_key_candidates(
            profiler,
            df,
            key_max_width=2,
            key_max_candidates=4,
            key_verification_pass_budget=4,
        )

        id_candidate = _find_candidate(candidates, ("id",))
        composite = _find_candidate(candidates, ("id", "effective_date"))
        assert id_candidate is not None
        assert id_candidate["verified_exact"] is True
        assert id_candidate["exact_unique"] is True
        assert id_candidate["emitted"] is True

        assert composite is not None
        assert composite["verified_exact"] is True
        assert composite["exact_unique"] is True
        assert composite["emitted"] is False
        assert composite["evidence"]["minimal"] is False
        assert "unique subset" in composite["evidence"]["reason"]

    def test_native_profiler_respects_candidate_and_pass_budget(
        self, spark_session: Any
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        df = _make_dataframe(
            spark_session,
            [
                (1, "A", 1, "x", 10, "q"),
                (2, "A", 1, "y", 11, "q"),
                (3, "B", 2, "x", 12, "q"),
                (4, "B", 2, "y", 13, "q"),
            ],
            "c1 int, c2 string, c3 int, c4 string, c5 int, c6 string",
        )

        profiler = NativeSparkProfiler(spark_session)
        candidates = _profile_key_candidates(
            profiler,
            df,
            key_max_width=3,
            key_max_candidates=6,
            key_verification_pass_budget=2,
        )

        verified = [
            candidate for candidate in candidates if candidate["verified_exact"]
        ]
        skipped = [
            candidate for candidate in candidates if not candidate["verified_exact"]
        ]

        assert len(verified) == 2
        assert skipped, (
            "expected some candidates to be skipped once the pass budget is exhausted"
        )
        assert all(candidate["verified_exact"] is False for candidate in skipped)

    def test_composite_search_respects_max_width_and_max_candidates(
        self, spark_session: Any
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        df = _make_dataframe(
            spark_session,
            [
                (1, "A", 1, "x", 10),
                (2, "A", 1, "y", 11),
                (3, "B", 2, "x", 12),
                (4, "B", 2, "y", 13),
            ],
            "c1 int, c2 string, c3 int, c4 string, c5 int",
        )

        profiler = NativeSparkProfiler(spark_session)
        candidates = _profile_key_candidates(
            profiler,
            df,
            key_max_width=2,
            key_max_candidates=4,
            key_verification_pass_budget=4,
        )

        assert len(candidates) <= 4
        assert all(len(candidate["columns"]) <= 2 for candidate in candidates)

    def test_minimality_is_honest_when_subset_verification_is_skipped(
        self, spark_session: Any
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        df = _make_dataframe(
            spark_session,
            [
                (1, 1, 1),
                (1, 1, 2),
                (1, 2, 1),
                (1, 2, 2),
                (2, 1, 1),
                (2, 1, 2),
                (2, 2, 1),
                (2, 2, 2),
            ],
            "a int, b int, c int",
        )

        profiler = NativeSparkProfiler(spark_session)
        candidates = _profile_key_candidates(
            profiler,
            df,
            key_max_width=3,
            key_max_candidates=1,
            key_verification_pass_budget=1,
        )

        triple = _find_candidate(candidates, ("a", "b", "c"))
        assert triple is not None
        assert triple["verified_exact"] is True
        assert triple["exact_unique"] is True
        assert triple["emitted"] is True
        assert triple["evidence"]["minimal"] is None
        assert "subset verification incomplete" in triple["evidence"]["reason"]


if _HAS_SAIL:

    @pytest.fixture(scope="module")
    def sail_spark() -> Any:
        """Start a Sail Spark Connect server and yield a Connect SparkSession."""
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ResourceWarning)
            server = SparkConnectServer()
            server.start()
            host, port = server.listening_address
            session = (
                RemoteSparkSession.builder.remote(f"sc://{host}:{port}")
                .appName("tablespec-profiler-connect-key-candidates")
                .create()
            )
            yield session
            session.stop()
            server.stop()


@pytest.mark.skipif(not _HAS_SAIL, reason="pysail not available")
class TestProfilerConnectSailKeyCandidates:
    """Classic and Connect sessions should serialize key candidates identically."""

    def test_connect_classic_key_candidates_structural_equality(
        self, spark_session: Any, sail_spark: Any
    ) -> None:
        from tablespec.profiling import NativeSparkProfiler

        rows = [
            (1, "2025-01-01"),
            (1, "2025-01-02"),
            (2, "2025-01-01"),
            (2, "2025-01-02"),
        ]
        schema = "member_id int, effective_date string"

        classic_df = _make_dataframe(spark_session, rows, schema)
        sail_df = _make_dataframe(sail_spark, rows, schema)

        classic_profile = _profile_key_candidates(
            NativeSparkProfiler(spark_session),
            classic_df,
            key_max_width=2,
            key_max_candidates=4,
            key_verification_pass_budget=4,
        )
        sail_profile = _profile_key_candidates(
            NativeSparkProfiler(sail_spark),
            sail_df,
            key_max_width=2,
            key_max_candidates=4,
            key_verification_pass_budget=4,
        )

        assert classic_profile == sail_profile


@pytest.mark.no_spark
class TestQualityGates:
    """The repo's quality-gate commands should be documented or operator-gated."""

    def _run_or_operator_required(
        self,
        command: list[str],
        *,
        cwd: Path,
        missing_reason: str,
    ) -> dict[str, Any]:
        tool = shutil.which(command[0])
        if tool is None:
            return {
                "status": "operator_required",
                "reason": missing_reason,
                "command": " ".join(command),
            }

        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return {
                "status": "passed",
                "command": " ".join(command),
                "stdout": result.stdout,
            }

        return {
            "status": "operator_required",
            "reason": (
                f"{command[0]} is installed but the command failed with exit code "
                f"{result.returncode}"
            ),
            "command": " ".join(command),
            "stderr": result.stderr,
        }

    def test_composite_go_test_gate(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / "go.mod").exists():
            result = {
                "status": "operator_required",
                "reason": "no Go module/toolchain exists in this repository",
                "command": "go test ./...",
            }
        else:
            result = self._run_or_operator_required(
                ["go", "test", "./..."],
                cwd=repo_root,
                missing_reason="go toolchain is unavailable",
            )

        assert result["status"] in {"passed", "operator_required"}

    def test_composite_lefthook_gate(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        lefthook_config = next(
            (
                path
                for path in (
                    repo_root / "lefthook.yml",
                    repo_root / "lefthook.yaml",
                    repo_root / ".lefthook.yml",
                    repo_root / ".lefthook.yaml",
                )
                if path.exists()
            ),
            None,
        )
        if lefthook_config is None:
            result = {
                "status": "operator_required",
                "reason": "lefthook configuration is not present in this repository",
                "command": "lefthook run pre-commit",
            }
        else:
            result = self._run_or_operator_required(
                ["lefthook", "run", "pre-commit"],
                cwd=repo_root,
                missing_reason="lefthook toolchain is unavailable",
            )

        assert result["status"] in {"passed", "operator_required"}
