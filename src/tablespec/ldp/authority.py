# SPDX-License-Identifier: MIT OR Apache-2.0
"""Explicit serialized-job authority; it never asserts distributed fencing."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExclusiveJobValidation(BaseModel):
    """Backend facts evaluated by the coordinator, with a retained receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    job_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    task_key: str = Field(min_length=1)
    observed_active_run_id: int = Field(gt=0)
    job_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    evidence_ref: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SerializedJobAuthority(BaseModel):
    """Opt-in authority pinned to one backend job, run, task and code artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    kind: Literal["serialized_job_execution"]
    job_id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    task_key: str = Field(min_length=1)
    job_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_concurrent_runs: Literal[1]
    queue_enabled: Literal[False]
    exclusive_validation: ExclusiveJobValidation

    @field_validator("max_concurrent_runs", mode="before")
    @classmethod
    def exact_concurrency(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("concurrency must be integer one")
        return value

    @field_validator("queue_enabled", mode="before")
    @classmethod
    def exact_queue(cls, value):
        if value is not False:
            raise ValueError("queue must be boolean false")
        return value


def assess_serialized_authority(authority, policy, now, max_age_seconds):
    """Compare evaluated facts with the expected deployment, never self-select."""
    issues = []
    if policy != "allow_serialized_job_execution":
        issues.append(
            ("FENCED_WRITER_REQUIRED", "Publication policy requires a fenced writer.")
        )
    observed = authority.exclusive_validation
    if (
        any(
            getattr(authority, name) != getattr(observed, name)
            for name in (
                "job_id",
                "run_id",
                "task_key",
                "job_definition_sha256",
                "code_sha256",
            )
        )
        or observed.observed_active_run_id != authority.run_id
    ):
        issues.append(
            (
                "JOB_AUTHORITY_MISMATCH",
                "Evaluated backend facts differ from the pinned job/run/task/code.",
            )
        )
    if (
        observed.observed_at.tzinfo is None
        or not 0 <= (now - observed.observed_at).total_seconds() < max_age_seconds
    ):
        issues.append(
            (
                "JOB_AUTHORITY_STALE",
                "Exclusive job observation is future, naive or stale.",
            )
        )
    return issues
