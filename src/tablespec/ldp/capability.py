# SPDX-License-Identifier: MIT OR Apache-2.0
"""Typed LDP declarations and readiness contracts, separate from execution."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tablespec.models.umf import DeltaAppendSource, DeltaIdentityScope, UMF

MAX_GROUP_ITEMS = 128
MAX_GROUP_BYTES = 96 * 1024 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, populate_by_name=True
    )


class RevisionPolicy(StrictModel):
    """Field mappings and immutable-revision semantics for the declared source."""

    record_id: str = Field(default="record_id", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    record_revision: str = Field(
        default="record_revision", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    record_kind: str = Field(default="record_kind", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    delivery_sequence: str = Field(
        default="delivery_seq", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    content_hash: str = Field(
        default="record_sha256", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"
    )
    replay: Literal["same_sequence_and_canonical_bytes"] = (
        "same_sequence_and_canonical_bytes"
    )
    conflict: Literal["block_and_retain_evidence"] = "block_and_retain_evidence"
    retention: Literal["all_revisions"] = "all_revisions"
    latest_projection: Literal["separate"] = "separate"
    reconstruction: Literal["bounded_chunk_codec"] = "bounded_chunk_codec"


class ArchiveBinding(StrictModel):
    """Declared append-only target contract for revision and conflict events."""

    raw_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
    )
    target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
    )
    sequence_decisions_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
    )
    fact_events_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
    )
    latest_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    archive_schema: dict[str, Literal["string", "long"]] = Field(alias="schema")
    identity_fields: list[str]
    revision_key_fields: list[str]
    delivery_key_fields: list[str]
    write_mode: Literal["append_only"] = "append_only"

    @model_validator(mode="after")
    def validate_archive_contract(self) -> ArchiveBinding:
        if len(set(self.identity_fields)) != len(self.identity_fields):
            raise ValueError("archive identity fields must be unique")
        if len(set(self.revision_key_fields)) != len(self.revision_key_fields):
            raise ValueError("archive revision key fields must be unique")
        if len(set(self.delivery_key_fields)) != len(self.delivery_key_fields):
            raise ValueError("archive delivery key fields must be unique")
        return self


class TypedSchemaBinding(StrictModel):
    schema_id: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_uri: str = Field(min_length=1)


class TransformStageBinding(StrictModel):
    """One typed callable stage from an immutable external adapter closure."""

    stage_id: str = Field(min_length=1)
    role: Literal["validate_raw_item", "reconstruct_revision"]
    entrypoint: str = Field(pattern=r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")
    input: TypedSchemaBinding
    output: TypedSchemaBinding
    group_by: list[str] = Field(default_factory=list)
    data_rejection_exceptions: list[str] = Field(default_factory=list)


class ExternalTransformBinding(StrictModel):
    """Immutable executable adapter closure and declared typed call stages."""

    transform_id: str = Field(min_length=1)
    artifact_uri: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Hash of complete immutable executable closure.",
    )
    stages: list[TransformStageBinding] = Field(min_length=2)
    max_group_items: int = Field(default=MAX_GROUP_ITEMS, ge=1, le=MAX_GROUP_ITEMS)
    max_group_bytes: int = Field(default=MAX_GROUP_BYTES, ge=1, le=MAX_GROUP_BYTES)

    @model_validator(mode="after")
    def validate_stages(self) -> ExternalTransformBinding:
        ids = [stage.stage_id for stage in self.stages]
        roles = [stage.role for stage in self.stages]
        if len(set(ids)) != len(ids) or set(roles) != {
            "validate_raw_item",
            "reconstruct_revision",
        }:
            raise ValueError(
                "transform requires unique stage IDs and one validator/reconstructor stage"
            )
        if any(
            not re.fullmatch(r"[A-Za-z_]\w*", name)
            for stage in self.stages
            for name in stage.data_rejection_exceptions
        ):
            raise ValueError(
                "data rejection exception names must be simple pinned-module class names"
            )
        return self


class LdpCapability(StrictModel):
    source: DeltaAppendSource
    revisions: RevisionPolicy
    transform: ExternalTransformBinding
    archive: ArchiveBinding
    required_dependencies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pipeline_bindings(self) -> LdpCapability:
        if len(set(self.required_dependencies)) != len(self.required_dependencies):
            raise ValueError("required dependencies must be unique")
        scope = list(DeltaIdentityScope.model_fields)
        expected_group = scope + [
            self.revisions.record_id,
            self.revisions.record_revision,
        ]
        if self.archive.identity_fields != scope:
            raise ValueError(
                f"archive identity_fields must exactly preserve source identity {scope}"
            )
        expected_revision_key = scope + [
            self.revisions.record_id,
            self.revisions.record_revision,
        ]
        expected_delivery_key = scope + ["delivery_sequence"]
        expected_archive_schema = {
            **{field: "string" for field in scope},
            "event_type": "string",
            "delivery_sequence": "long",
            "record_id": "string",
            "record_revision": "long",
            "content_hash": "string",
            "payload_json": "string",
            "record_sha256": "string",
            "disposition": "string",
            "reason_code": "string",
            "evidence_json": "string",
            "event_order": "long",
        }
        if self.archive.archive_schema != expected_archive_schema:
            raise ValueError(
                "archive schema must exactly declare source identity and LDP event fields/physical types"
            )
        if self.archive.revision_key_fields != expected_revision_key:
            raise ValueError(
                f"archive revision_key_fields must be {expected_revision_key}"
            )
        if self.archive.delivery_key_fields != expected_delivery_key:
            raise ValueError(
                f"archive delivery_key_fields must be {expected_delivery_key}"
            )
        namespace = ".".join(self.source.table.split(".")[:2])
        targets = (
            self.archive.raw_target,
            self.archive.target,
            self.archive.sequence_decisions_target,
            self.archive.fact_events_target,
            self.archive.latest_target,
        )
        if any(".".join(target.split(".")[:2]) != namespace for target in targets):
            raise ValueError(
                "all generated LDP targets must be fully qualified in the source catalog/schema"
            )
        if len(set(targets)) != len(targets):
            raise ValueError("generated LDP targets must be distinct")
        reconstruct = next(
            s for s in self.transform.stages if s.role == "reconstruct_revision"
        )
        if reconstruct.group_by != expected_group:
            raise ValueError(
                f"reconstruction group_by must exactly bind source scope and revision identity {expected_group}"
            )
        return self


class CoordinatorEvidence(StrictModel):
    """Fresh evaluated publication-barrier facts supplied by Erg."""

    snapshot_id: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_table: str = Field(min_length=1)
    declared_starting_version: int = Field(ge=0)
    current_source_version: int = Field(ge=0)
    transform_id: str = Field(min_length=1)
    transform_version: str = Field(min_length=1)
    transform_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_dependency_ids: list[str]
    validated_dependency_ids: list[str]
    dependency_pins: dict[str, int]
    dependency_snapshot_sha256: dict[str, str]
    conflict_check: Literal["clear", "conflicts"]
    conflict_query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conflict_evidence_refs: list[str] = Field(default_factory=list)
    materialized_through: int = Field(ge=0)
    projected_through: int = Field(ge=0)
    evaluated_at: datetime
    evidence_expires_at: datetime
    writer_lease_ref: str = Field(min_length=1)
    writer_fence: str = Field(min_length=1)
    writer_lease_expires_at: datetime

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> CoordinatorEvidence:
        if self.projected_through > self.materialized_through:
            raise ValueError("projected cursor cannot exceed materialized cursor")
        if self.conflict_check == "conflicts" and not self.conflict_evidence_refs:
            raise ValueError("conflict results require durable evidence references")
        if self.conflict_check == "clear" and self.conflict_evidence_refs:
            raise ValueError("a clear conflict result cannot carry conflict references")
        if set(self.validated_dependency_ids) != set(self.required_dependency_ids):
            raise ValueError(
                "validated dependency set must exactly match required dependencies"
            )
        if set(self.dependency_pins) != set(self.required_dependency_ids):
            raise ValueError(
                "every required dependency must have a pinned source version"
            )
        if set(self.dependency_snapshot_sha256) != set(self.required_dependency_ids):
            raise ValueError(
                "every required dependency must bind to an evaluated snapshot hash"
            )
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in self.dependency_snapshot_sha256.values()
        ):
            raise ValueError(
                "dependency snapshot hashes must be lowercase SHA-256 values"
            )
        if self.writer_lease_expires_at <= self.evaluated_at:
            raise ValueError("writer lease must outlive the coordinator evaluation")
        if self.evidence_expires_at <= self.evaluated_at:
            raise ValueError("coordinator evidence must expire after its evaluation")
        return self


class ReadinessIssue(StrictModel):
    code: str
    message: str
    evidence_ref: str | None = None


class LdpReadinessReport(StrictModel):
    status: Literal["ready", "blocked"]
    table: str
    source_table: str
    starting_version: int
    transform_id: str
    transform_version: str
    transform_sha256: str
    group_by: list[str]
    generated_pipeline_dependencies: list[str]
    required_dependency_ids: list[str]
    max_group_items: int
    max_group_bytes: int
    blockers: list[ReadinessIssue] = Field(default_factory=list)
    cross_table_atomicity: Literal["not_asserted"] = "not_asserted"


class PublicationReadinessReport(StrictModel):
    status: Literal["ready", "blocked"]
    table: str
    snapshot_id: str
    snapshot_sha256: str
    current_source_version: int
    dependencies: list[str]
    dependency_pins: dict[str, int]
    dependency_snapshot_sha256: dict[str, str]
    materialized_through: int
    projected_through: int
    conflict_evidence_refs: list[str]
    writer_lease_ref: str
    writer_fence: str
    blockers: list[ReadinessIssue] = Field(default_factory=list)
    cross_table_atomicity: Literal["not_asserted"] = "not_asserted"


def capability_for_umf(umf: UMF) -> LdpCapability:
    """Validate one UMF's typed Delta source and TableSpec extension declaration."""
    source = umf.effective_source()
    if not isinstance(source, DeltaAppendSource):
        raise ValueError(
            f"{umf.table_name}: advanced LDP capability requires a typed Delta append source"
        )
    if umf.metadata is None or not umf.metadata.ldp:
        raise ValueError(
            f"{umf.table_name}: LDP revision/transform declaration is required"
        )
    declaration = dict(umf.metadata.ldp)
    declaration["source"] = source.model_dump(mode="python")
    return LdpCapability.model_validate(declaration)


def assess_ldp_readiness(umfs: list[UMF]) -> dict[str, LdpReadinessReport]:
    """Static deterministic readiness; no runtime lease or coordinator proof required."""
    reports: dict[str, LdpReadinessReport] = {}
    for umf in umfs:
        source = umf.effective_source()
        has_declaration = umf.metadata is not None and bool(umf.metadata.ldp)
        if not has_declaration and getattr(source, "kind", None) != "delta":
            continue
        capability = capability_for_umf(umf)
        reports[umf.table_name] = LdpReadinessReport(
            status="ready",
            table=umf.table_name,
            source_table=capability.source.table,
            starting_version=capability.source.starting_version,
            transform_id=capability.transform.transform_id,
            transform_version=capability.transform.version,
            transform_sha256=capability.transform.sha256,
            group_by=next(
                s.group_by
                for s in capability.transform.stages
                if s.role == "reconstruct_revision"
            ),
            generated_pipeline_dependencies=[
                capability.archive.raw_target,
                capability.archive.sequence_decisions_target,
                capability.archive.target,
                capability.archive.fact_events_target,
                capability.archive.latest_target,
            ],
            required_dependency_ids=sorted(
                set(capability.required_dependencies)
                | {
                    capability.archive.raw_target,
                    capability.archive.sequence_decisions_target,
                    capability.archive.target,
                    capability.archive.fact_events_target,
                    capability.archive.latest_target,
                }
            ),
            max_group_items=capability.transform.max_group_items,
            max_group_bytes=capability.transform.max_group_bytes,
        )
    return reports


def assess_publication_readiness(
    table: str, capability: LdpCapability, evidence: CoordinatorEvidence | None
) -> PublicationReadinessReport:
    """Evaluate current coordinator evidence for the publication barrier only."""
    blockers: list[ReadinessIssue] = []
    if evidence is None:
        raise ValueError("publication readiness requires fresh coordinator evidence")
    if evidence.source_table != capability.source.table:
        blockers.append(
            ReadinessIssue(
                code="SOURCE_TABLE_MISMATCH",
                message="Snapshot source table differs from declaration.",
            )
        )
    if evidence.declared_starting_version != capability.source.starting_version:
        blockers.append(
            ReadinessIssue(
                code="START_VERSION_MISMATCH",
                message="Coordinator start boundary differs from declaration.",
            )
        )
    if evidence.current_source_version < evidence.declared_starting_version:
        blockers.append(
            ReadinessIssue(
                code="SOURCE_VERSION_REGRESSION",
                message="Current source snapshot precedes the declared start boundary.",
            )
        )
    if (
        evidence.transform_id,
        evidence.transform_version,
        evidence.transform_sha256,
    ) != (
        capability.transform.transform_id,
        capability.transform.version,
        capability.transform.sha256,
    ):
        blockers.append(
            ReadinessIssue(
                code="TRANSFORM_PIN_MISMATCH",
                message="Coordinator transform closure differs from declaration.",
            )
        )
    if evidence.evaluated_at.tzinfo is None or evidence.evaluated_at > datetime.now(
        timezone.utc
    ):
        blockers.append(
            ReadinessIssue(
                code="EVIDENCE_TIME_INVALID",
                message="Coordinator evidence must have a timezone-aware, non-future evaluation time.",
            )
        )
    if (
        evidence.evidence_expires_at.tzinfo is None
        or evidence.evidence_expires_at <= datetime.now(timezone.utc)
    ):
        blockers.append(
            ReadinessIssue(
                code="EVIDENCE_STALE",
                message="Coordinator snapshot evidence has expired.",
            )
        )
    generated_dependencies = {
        capability.archive.raw_target,
        capability.archive.sequence_decisions_target,
        capability.archive.target,
        capability.archive.fact_events_target,
        capability.archive.latest_target,
    }
    derived_dependencies = (
        set(capability.required_dependencies) | generated_dependencies
    )
    if set(evidence.required_dependency_ids) != derived_dependencies:
        blockers.append(
            ReadinessIssue(
                code="DEPENDENCY_SET_MISMATCH",
                message="Coordinator dependencies differ from the declared and generated dependency set.",
            )
        )
    if evidence.conflict_check != "clear":
        blockers.append(
            ReadinessIssue(
                code="CONFLICT_GATE_BLOCKED",
                message="Coordinator conflict check did not pass.",
            )
        )
    now = datetime.now(timezone.utc)
    if (
        evidence.writer_lease_expires_at.tzinfo is None
        or evidence.writer_lease_expires_at <= now
    ):
        blockers.append(
            ReadinessIssue(
                code="WRITER_LEASE_STALE",
                message="Publication requires a fresh, unexpired fenced writer lease.",
            )
        )
    return PublicationReadinessReport(
        status="blocked" if blockers else "ready",
        table=table,
        snapshot_id=evidence.snapshot_id,
        snapshot_sha256=evidence.snapshot_sha256,
        current_source_version=evidence.current_source_version,
        dependencies=evidence.required_dependency_ids,
        dependency_pins=evidence.dependency_pins,
        dependency_snapshot_sha256=evidence.dependency_snapshot_sha256,
        materialized_through=evidence.materialized_through,
        projected_through=evidence.projected_through,
        conflict_evidence_refs=evidence.conflict_evidence_refs,
        writer_lease_ref=evidence.writer_lease_ref,
        writer_fence=evidence.writer_fence,
        blockers=blockers,
    )


def invocation_manifest(table_name: str, capability: LdpCapability) -> dict:
    """Describe an executable, hash-pinned codec call and its pre-collect obligations."""
    return {
        "format": "tablespec.ldp-transform-invocation/2",
        "table": table_name,
        "source": capability.source.model_dump(mode="json"),
        "revision_policy": capability.revisions.model_dump(mode="json"),
        "transform": capability.transform.model_dump(mode="json"),
        "archive": capability.archive.model_dump(mode="json", by_alias=True),
        "declared_dependencies": capability.required_dependencies,
        "generated_pipeline_dependencies": [
            capability.archive.raw_target,
            capability.archive.sequence_decisions_target,
            capability.archive.target,
            capability.archive.fact_events_target,
            capability.archive.latest_target,
        ],
        "required_dependency_ids": sorted(
            set(capability.required_dependencies)
            | {
                capability.archive.raw_target,
                capability.archive.sequence_decisions_target,
                capability.archive.target,
                capability.archive.fact_events_target,
                capability.archive.latest_target,
            }
        ),
        "invocation": {
            "stage_order": [stage.stage_id for stage in capability.transform.stages],
            "dataflow": [
                {
                    "op": "scope_filter",
                    "values": capability.source.identity_scope.model_dump(mode="json"),
                    "before": "adapter_validation",
                },
                {
                    "op": "typed_call",
                    "stage_id": next(
                        s.stage_id
                        for s in capability.transform.stages
                        if s.role == "validate_raw_item"
                    ),
                },
                {
                    "op": "retain_validation_conflicts",
                    "payload": "redacted_identity_and_reason_code",
                },
                {
                    "op": "detect_sequence_conflicts",
                    "group_by": [
                        *DeltaIdentityScope.model_fields,
                        capability.revisions.delivery_sequence,
                    ],
                    "comparison": "exact_canonical_item_bytes",
                    "before": "replay_collapse",
                },
                {
                    "op": "collapse_exact_replays",
                    "group_by": [
                        *DeltaIdentityScope.model_fields,
                        capability.revisions.delivery_sequence,
                    ],
                },
                {
                    "op": "bound_revision_groups_before_collect",
                    "group_by": next(
                        s.group_by
                        for s in capability.transform.stages
                        if s.role == "reconstruct_revision"
                    ),
                    "max_items": capability.transform.max_group_items,
                    "max_utf8_bytes": capability.transform.max_group_bytes,
                },
                {
                    "op": "typed_call",
                    "stage_id": next(
                        s.stage_id
                        for s in capability.transform.stages
                        if s.role == "reconstruct_revision"
                    ),
                },
                {
                    "op": "retain_pending_chunks_across_updates",
                    "stateful_operator": "transformWithStateInPandas",
                    "watermark_eviction": False,
                    "ttl": None,
                },
                {
                    "op": "append_immutable_revision_archive",
                    "target": capability.archive.target,
                    "schema": capability.archive.model_dump(mode="json", by_alias=True)[
                        "schema"
                    ],
                    "write_mode": "append_only",
                },
                {"op": "derive_latest_separately"},
            ],
            "preconditions": [
                "filter rows to the exact identity_scope values before codec validation",
                "validate outer identity and envelope against canonical item bytes with checked_item",
                "detect same-scope delivery_seq conflicts before deduplication or content-hash grouping",
                "collapse only exact canonical-byte replays for the same delivery_seq",
                "apply item and byte bounds before collecting each revision group",
                "invoke each declared typed stage at its declared grouping boundary",
                "retain pending incomplete chunks across source updates; do not watermark-evict them",
                "preserve every complete revision; derive latest state separately",
            ],
            "max_group_items": capability.transform.max_group_items,
            "max_group_bytes": capability.transform.max_group_bytes,
        },
        "cross_table_atomicity": "not_asserted",
        "runtime_profile": {
            "api": "PySpark transformWithStateInPandas with Lakeflow Pipelines",
            "minimum_databricks_runtime": "16.3",
            "minimum_access_mode": "standard",
            "runtime_provided_dependencies": ["pyspark", "pandas", "pyarrow"],
            "runtime_dependency_versions": "record from the selected runtime before qualification",
            "local_test_extra": "tablespec[spark] is for local tests; do not install it over Databricks runtime packages",
            "state_ttl": "disabled",
            "pending_state_eviction": False,
            "native_runtime_qualification": "not_performed",
        },
    }


__all__ = [
    "CoordinatorEvidence",
    "ExternalTransformBinding",
    "LdpCapability",
    "LdpReadinessReport",
    "PublicationReadinessReport",
    "ReadinessIssue",
    "RevisionPolicy",
    "TypedSchemaBinding",
    "TransformStageBinding",
    "assess_ldp_readiness",
    "assess_publication_readiness",
    "capability_for_umf",
    "invocation_manifest",
]
