from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tablespec.ldp import (
    CoordinatorEvidence,
    SerializedJobAuthority,
    assess_publication_readiness,
)
from tablespec.ldp.capability import capability_for_umf
from tests.ldp.test_ldp_capability import _evidence, _spec

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def authority():
    return dict(
        kind="serialized_job_execution",
        job_id=123,
        run_id=456,
        task_key="publish",
        job_definition_sha256="a" * 64,
        code_sha256="b" * 64,
        max_concurrent_runs=1,
        queue_enabled=False,
        exclusive_validation=dict(
            job_id=123,
            run_id=456,
            task_key="publish",
            observed_active_run_id=456,
            job_definition_sha256="a" * 64,
            code_sha256="b" * 64,
            observed_at=datetime.now(timezone.utc),
            evidence_ref="qualification/backend-observation.json",
            evidence_sha256="c" * 64,
        ),
    )


def evidence(value=None):
    data = _evidence().model_dump()
    data.update(
        writer_lease_ref=None,
        writer_fence=None,
        writer_lease_expires_at=None,
        execution_authority=authority() if value is None else value,
    )
    return CoordinatorEvidence.model_validate(data)


def readiness(value, **kwargs):
    return assess_publication_readiness(
        "events", capability_for_umf(_spec()), value, **kwargs
    )


def test_serialized_authority_requires_explicit_policy_and_never_claims_fencing():
    value = evidence()
    blocked = readiness(value)
    assert blocked.status == "blocked"
    assert "FENCED_WRITER_REQUIRED" in [issue.code for issue in blocked.blockers]
    allowed = readiness(value, publication_policy="allow_serialized_job_execution")
    assert allowed.status == "ready"
    assert allowed.authority_kind == "serialized_job_execution"
    assert allowed.writer_fence is None and allowed.writer_lease_ref is None
    assert allowed.execution_authority.run_id == 456
    assert allowed.cross_table_atomicity == "not_asserted"


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("job_id", 999),
        ("run_id", 999),
        ("observed_active_run_id", 999),
        ("task_key", "other"),
        ("job_definition_sha256", "d" * 64),
        ("code_sha256", "d" * 64),
    ],
)
def test_observed_backend_must_match_all_pinned_authority_fields(field, wrong):
    value = authority()
    value["exclusive_validation"][field] = wrong
    report = readiness(
        evidence(value), publication_policy="allow_serialized_job_execution"
    )
    assert report.status == "blocked"
    assert "JOB_AUTHORITY_MISMATCH" in [issue.code for issue in report.blockers]


@pytest.mark.parametrize("age", [-10, 61])
def test_future_or_stale_observation_blocks_serialized_publication(age):
    value = authority()
    value["exclusive_validation"]["observed_at"] = datetime.now(
        timezone.utc
    ) - timedelta(seconds=age)
    report = readiness(
        evidence(value), publication_policy="allow_serialized_job_execution"
    )
    assert report.status == "blocked"
    assert "JOB_AUTHORITY_STALE" in [issue.code for issue in report.blockers]


def test_naive_observation_is_blocked_and_freshness_is_configured():
    value = authority()
    value["exclusive_validation"]["observed_at"] = datetime.now()
    assert (
        readiness(
            evidence(value), publication_policy="allow_serialized_job_execution"
        ).status
        == "blocked"
    )
    value = authority()
    value["exclusive_validation"]["observed_at"] -= timedelta(seconds=10)
    assert (
        readiness(
            evidence(value),
            publication_policy="allow_serialized_job_execution",
            max_authority_age_seconds=5,
        ).status
        == "blocked"
    )
    for invalid in (0, 301, True):
        with pytest.raises(ValueError):
            readiness(evidence(), max_authority_age_seconds=invalid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("queue_enabled", True),
        ("queue_enabled", 0),
        ("max_concurrent_runs", True),
        ("max_concurrent_runs", 2),
        ("kind", "fenced_lease"),
        ("code_sha256", "not-a-hash"),
    ],
)
def test_invalid_job_authority_cannot_enter_readiness(field, value):
    data = authority()
    data[field] = value
    with pytest.raises(ValidationError):
        SerializedJobAuthority.model_validate(data)


def test_missing_and_hybrid_authority_fail_validation():
    data = _evidence().model_dump()
    data["writer_fence"] = None
    with pytest.raises(ValidationError):
        CoordinatorEvidence.model_validate(data)
    data = _evidence().model_dump()
    data["execution_authority"] = authority()
    with pytest.raises(ValidationError):
        CoordinatorEvidence.model_validate(data)
    del data["execution_authority"]
    assert readiness(CoordinatorEvidence.model_validate(data)).status == "ready"
    with pytest.raises(ValueError):
        readiness(evidence(), publication_policy="implicit")
