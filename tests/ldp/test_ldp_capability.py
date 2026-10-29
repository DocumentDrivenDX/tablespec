from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from tablespec.ldp import (
    CoordinatorEvidence,
    LdpProjectError,
    assess_ldp_readiness,
    assess_publication_readiness,
    generate_ldp_project,
)
from tablespec.ldp.execution import as_row_mapping, execute_revision_graph
from tablespec.models.umf import UMF, UMFColumn

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

HASH = "a" * 64


def _spec() -> UMF:
    return UMF(
        version="1.0",
        table_name="events",
        source={
            "kind": "delta",
            "table": "catalog.schema.events",
            "read_mode": "append_stream",
            "starting_version": 12,
            "identity_scope": {
                "enrollment_id": "synthetic-ldp-qualification",
                "installation_id": "fabricated",
                "destination_generation": "synthetic-only-v1",
            },
        },
        columns=[{"name": "record_id", "data_type": "VARCHAR"}],
        metadata={
            "ldp": {
                "required_dependencies": ["revision-facts"],
                "revisions": {
                    "record_id": "record_id",
                    "record_revision": "record_revision",
                    "record_kind": "record_kind",
                    "delivery_sequence": "delivery_seq",
                    "content_hash": "record_sha256",
                    "replay": "same_sequence_and_canonical_bytes",
                    "conflict": "block_and_retain_evidence",
                    "retention": "all_revisions",
                    "latest_projection": "separate",
                    "reconstruction": "bounded_chunk_codec",
                },
                "transform": {
                    "transform_id": "synthetic.revision-codec",
                    "artifact_uri": "https://example.invalid/fixtures/synthetic-adapter.zip",
                    "version": "1.0.0",
                    "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                    "stages": [
                        {
                            "stage_id": "validate-item",
                            "role": "validate_raw_item",
                            "entrypoint": "synthetic_adapter.codec.checked_item",
                            "input": {
                                "schema_id": "urn:example:synthetic:validation-input:1.0.0",
                                "version": "1.0.0",
                                "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                                "schema_uri": "https://example.invalid/fixtures/validation-input.json",
                            },
                            "output": {
                                "schema_id": "urn:example:synthetic:validation-output:1.0.0",
                                "version": "1.0.0",
                                "sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                                "schema_uri": "https://example.invalid/fixtures/validation-output.json",
                            },
                            "group_by": [],
                            "data_rejection_exceptions": ["RejectedItem"],
                        },
                        {
                            "stage_id": "reconstruct-revision",
                            "role": "reconstruct_revision",
                            "entrypoint": "synthetic_adapter.codec.reconstruct_revision",
                            "input": {
                                "schema_id": "urn:example:synthetic:reconstruction-input:1.0.0",
                                "version": "1.0.0",
                                "sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                                "schema_uri": "https://example.invalid/fixtures/reconstruction-input.json",
                            },
                            "output": {
                                "schema_id": "urn:example:synthetic:reconstruction-output:1.0.0",
                                "version": "1.0.0",
                                "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                                "schema_uri": "https://example.invalid/fixtures/reconstruction-output.json",
                            },
                            "group_by": [
                                "enrollment_id",
                                "installation_id",
                                "destination_generation",
                                "record_id",
                                "record_revision",
                            ],
                            "data_rejection_exceptions": ["RejectedItem"],
                        },
                    ],
                },
                "archive": {
                    "raw_target": "catalog.schema.raw_events",
                    "target": "catalog.schema.events_revision_archive",
                    "sequence_decisions_target": "catalog.schema.events_sequence_decisions",
                    "fact_events_target": "catalog.schema.events_revision_fact_events",
                    "latest_target": "catalog.schema.events_latest_revision",
                    "schema_version": "1.0.0",
                    "schema": {
                        "enrollment_id": "string",
                        "installation_id": "string",
                        "destination_generation": "string",
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
                    },
                    "identity_fields": [
                        "enrollment_id",
                        "installation_id",
                        "destination_generation",
                    ],
                    "revision_key_fields": [
                        "enrollment_id",
                        "installation_id",
                        "destination_generation",
                        "record_id",
                        "record_revision",
                    ],
                    "delivery_key_fields": [
                        "enrollment_id",
                        "installation_id",
                        "destination_generation",
                        "delivery_sequence",
                    ],
                    "write_mode": "append_only",
                },
            }
        },
    )


def _evidence(**updates) -> CoordinatorEvidence:
    values = {
        "snapshot_id": "snapshot-001",
        "snapshot_sha256": "b" * 64,
        "source_table": "catalog.schema.events",
        "declared_starting_version": 12,
        "current_source_version": 14,
        "transform_id": "synthetic.revision-codec",
        "transform_version": "1.0.0",
        "transform_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "required_dependency_ids": [
            "revision-facts",
            "catalog.schema.raw_events",
            "catalog.schema.events_sequence_decisions",
            "catalog.schema.events_revision_archive",
            "catalog.schema.events_revision_fact_events",
            "catalog.schema.events_latest_revision",
        ],
        "validated_dependency_ids": [
            "revision-facts",
            "catalog.schema.raw_events",
            "catalog.schema.events_sequence_decisions",
            "catalog.schema.events_revision_archive",
            "catalog.schema.events_revision_fact_events",
            "catalog.schema.events_latest_revision",
        ],
        "dependency_pins": {
            "revision-facts": 9,
            "catalog.schema.raw_events": 1,
            "catalog.schema.events_sequence_decisions": 1,
            "catalog.schema.events_revision_archive": 1,
            "catalog.schema.events_revision_fact_events": 1,
            "catalog.schema.events_latest_revision": 1,
        },
        "dependency_snapshot_sha256": {
            key: "e" * 64
            for key in [
                "revision-facts",
                "catalog.schema.raw_events",
                "catalog.schema.events_sequence_decisions",
                "catalog.schema.events_revision_archive",
                "catalog.schema.events_revision_fact_events",
                "catalog.schema.events_latest_revision",
            ]
        },
        "conflict_check": "clear",
        "conflict_query_sha256": "c" * 64,
        "materialized_through": 121,
        "projected_through": 120,
        "evaluated_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        "evidence_expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        "writer_lease_ref": "lease://synthetic/one-writer",
        "writer_fence": "fence-17",
        "writer_lease_expires_at": datetime.now(timezone.utc) + timedelta(days=365),
    }
    values.update(updates)
    return CoordinatorEvidence(**values)


def test_delta_source_requires_qualified_append_version_and_scope() -> None:
    with pytest.raises(ValidationError):
        UMF(
            version="1.0",
            table_name="events",
            source={
                "kind": "delta",
                "table": "events",
                "read_mode": "append_stream",
                "starting_version": 1,
            },
            columns=[{"name": "id", "data_type": "INTEGER"}],
        )
    with pytest.raises(ValidationError):
        UMF(
            version="1.0",
            table_name="events",
            source={
                "kind": "delta",
                "table": "catalog.schema.events",
                "read_mode": "update_stream",
                "starting_version": 1,
            },
            columns=[{"name": "id", "data_type": "INTEGER"}],
        )


def test_static_readiness_does_not_require_ephemeral_publication_lease() -> None:
    report = assess_ldp_readiness([_spec()])["events"]
    assert report.status == "ready"
    assert report.starting_version == 12
    assert report.cross_table_atomicity == "not_asserted"


def test_readiness_reports_pin_mismatch_and_conflict_evidence() -> None:
    evidence = _evidence(
        current_source_version=15,
        conflict_check="conflicts",
        conflict_evidence_refs=["conflict://synthetic/seq-4"],
    )
    from tablespec.ldp.capability import capability_for_umf

    report = assess_publication_readiness(
        "events", capability_for_umf(_spec()), evidence
    )
    assert report.status == "blocked"
    assert {issue.code for issue in report.blockers} == {"CONFLICT_GATE_BLOCKED"}
    assert report.conflict_evidence_refs == ["conflict://synthetic/seq-4"]


def test_generated_targets_are_mandatory_readiness_dependencies() -> None:
    from tablespec.ldp.capability import capability_for_umf

    report = assess_ldp_readiness([_spec()])["events"]
    generated = {
        "catalog.schema.raw_events",
        "catalog.schema.events_sequence_decisions",
        "catalog.schema.events_revision_archive",
        "catalog.schema.events_revision_fact_events",
        "catalog.schema.events_latest_revision",
    }
    assert set(report.generated_pipeline_dependencies) == generated
    assert set(report.required_dependency_ids) == generated | {"revision-facts"}

    capability = capability_for_umf(_spec())
    omitted = _evidence(
        required_dependency_ids=["revision-facts"],
        validated_dependency_ids=["revision-facts"],
        dependency_pins={"revision-facts": 9},
        dependency_snapshot_sha256={"revision-facts": "e" * 64},
    )
    result = assess_publication_readiness("events", capability, omitted)
    assert result.status == "blocked"
    assert "DEPENDENCY_SET_MISMATCH" in {item.code for item in result.blockers}


def test_transform_grouping_must_preserve_codec_identity_scope() -> None:
    spec = _spec()
    bad = spec.model_copy(deep=True)
    bad.metadata.ldp["transform"]["group_by"] = ["record_id", "record_revision"]
    with pytest.raises((ValidationError, ValueError)):
        assess_ldp_readiness([bad])


def test_generate_emits_pinned_transform_binding_and_is_deterministic() -> None:
    first = generate_ldp_project([_spec()])
    second = generate_ldp_project([_spec()])
    assert first == second
    raw = first["raw/raw_events.sql"]
    assert "catalog`.`schema`.`events" in raw
    assert "WITH (STARTINGVERSION=12)" in raw
    assert "enrollment_id` = 'synthetic-ldp-qualification'" in raw
    manifest = json.loads(first["bindings/events.json"])
    assert manifest["source"]["identity_scope"] == {
        "enrollment_id": "synthetic-ldp-qualification",
        "installation_id": "fabricated",
        "destination_generation": "synthetic-only-v1",
    }
    assert (
        manifest["transform"]["sha256"]
        == "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    )
    assert manifest["archive"]["target"] == "catalog.schema.events_revision_archive"
    assert manifest["archive"]["write_mode"] == "append_only"
    assert manifest["runtime_profile"]["minimum_databricks_runtime"] == "17.3"
    assert manifest["runtime_profile"]["runtime_provided_dependencies"] == [
        "pyspark",
        "pandas",
        "pyarrow",
    ]
    assert (
        "do not install it over Databricks runtime packages"
        in manifest["runtime_profile"]["local_test_extra"]
    )
    assert [s["entrypoint"] for s in manifest["transform"]["stages"]] == [
        "synthetic_adapter.codec.checked_item",
        "synthetic_adapter.codec.reconstruct_revision",
    ]
    assert "exact identity_scope values" in manifest["invocation"]["preconditions"][0]
    assert manifest["cross_table_atomicity"] == "not_asserted"
    assert [stage["op"] for stage in manifest["invocation"]["dataflow"]] == [
        "scope_filter",
        "typed_call",
        "retain_validation_conflicts",
        "detect_sequence_conflicts",
        "collapse_exact_replays",
        "bound_revision_groups_before_collect",
        "typed_call",
        "retain_pending_chunks_across_updates",
        "append_immutable_revision_archive",
        "derive_latest_separately",
    ]
    executor = first["pipeline/ldp_events.py"]
    compile(executor, "pipeline/ldp_events.py", "exec")
    assert "@dp.table(name=_SEQUENCE_TARGET" in executor
    assert "@dp.table(name=_ARCHIVE.target" in executor
    assert "transformWithStateInPandas" in executor
    assert "dp.create_auto_cdc_flow(" in executor
    assert "stored_as_scd_type=1" in executor
    assert "@dp.materialized_view" not in executor
    assert "LongType" in executor


def test_generated_revision_module_initializes_archive_schema_with_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute generated module setup to catch model/API alias collisions."""
    generated = generate_ldp_project([_spec()])["pipeline/ldp_events.py"]

    class SparkType:
        pass

    class LongType(SparkType):
        pass

    class StringType(SparkType):
        pass

    class StructField:
        def __init__(self, name: str, data_type: SparkType, nullable: bool) -> None:
            self.name = name
            self.dataType = data_type
            self.nullable = nullable

    class StructType:
        def __init__(self, fields: list[StructField]) -> None:
            self.fields = fields

    class Column:
        def __eq__(self, other: object) -> Column:
            return self

    registered: list[str] = []
    flows: list[dict[str, object]] = []

    def table(**kwargs: object):
        def decorate(function):
            registered.append(str(kwargs["name"]))
            return function

        return decorate

    dp = SimpleNamespace(
        table=table,
        create_streaming_table=lambda **kwargs: None,
        create_auto_cdc_flow=lambda **kwargs: flows.append(kwargs),
    )
    functions = SimpleNamespace(col=lambda name: Column(), lit=lambda value: value)
    spark_types = SimpleNamespace(
        StructType=StructType,
        StructField=StructField,
        LongType=LongType,
        StringType=StringType,
    )
    pyspark = ModuleType("pyspark")
    pyspark.__path__ = []  # type: ignore[attr-defined]
    pyspark.pipelines = dp  # type: ignore[attr-defined]
    sql = ModuleType("pyspark.sql")
    sql.__path__ = []  # type: ignore[attr-defined]
    sql.functions = functions  # type: ignore[attr-defined]
    sql.types = spark_types  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "pyspark", pyspark)
    monkeypatch.setitem(__import__("sys").modules, "pyspark.pipelines", dp)
    monkeypatch.setitem(__import__("sys").modules, "pyspark.sql", sql)
    monkeypatch.setitem(__import__("sys").modules, "pyspark.sql.functions", functions)
    monkeypatch.setitem(__import__("sys").modules, "pyspark.sql.types", spark_types)

    module = ModuleType("generated_ldp_events")
    exec(compile(generated, "pipeline/ldp_events.py", "exec"), module.__dict__)

    archive_fields = {field.name: field for field in module._ARCHIVE_SCHEMA.fields}
    assert isinstance(archive_fields["delivery_sequence"].dataType, LongType)
    assert isinstance(archive_fields["record_revision"].dataType, LongType)
    assert isinstance(archive_fields["event_type"].dataType, StringType)
    assert set(registered) == {
        "catalog.schema.events_sequence_decisions",
        "catalog.schema.events_revision_archive",
        "catalog.schema.events_revision_fact_events",
    }
    assert len(flows) == 1


def test_generated_delta_project_keeps_protocol_integer_fields_as_bigint() -> None:
    spec = _spec().model_copy(deep=True)
    spec.columns.extend(
        [
            UMFColumn(name="delivery_seq", data_type="INTEGER"),
            UMFColumn(name="record_revision", data_type="INTEGER"),
        ]
    )

    files = generate_ldp_project([spec])
    assert set(files) == {
        "raw/raw_events.sql",
        "bindings/events.json",
        "pipeline/ldp_events.py",
        "ingested/ingested_events.sql",
    }

    ingested = files["ingested/ingested_events.sql"]
    assert "cast(delivery_seq as BIGINT)" in ingested
    assert "AS delivery_seq" in ingested
    assert "cast(record_revision as BIGINT)" in ingested
    assert "AS record_revision" in ingested
    assert "regexp_replace(delivery_seq" not in ingested
    assert "regexp_replace(record_revision" not in ingested
    assert "cast(delivery_seq as INT)" not in ingested
    assert "cast(record_revision as INT)" not in ingested

    # The shared cast's exact 2**53+7 value is exercised in the companion
    # casting regression; this asserts the generated boundary uses that type.


def test_generate_refuses_missing_or_conflicting_readiness() -> None:
    missing = _spec()
    missing.metadata.ldp = None
    with pytest.raises(
        LdpProjectError, match="LDP revision/transform declaration is required"
    ):
        generate_ldp_project([missing])


def test_typed_ldp_uses_pipeline_v02_without_redefining_v01() -> None:
    from tablespec.extensions.umf import (
        EXTENSION_ID,
        EXTENSION_VERSION,
        EXTENSION_VERSION_TYPED_LDP,
        pipeline_registry,
    )

    registry = pipeline_registry()
    old_entry = registry.get(EXTENSION_ID, "0.1.0")
    typed_entry = registry.get(EXTENSION_ID, "0.2.0")
    assert old_entry is not None and typed_entry is not None
    assert old_entry[0].schema["$id"] == "urn:tablespec.pipeline:0.1.0"
    assert typed_entry[0].schema["$id"] == "urn:tablespec.pipeline:0.2.0"
    assert EXTENSION_VERSION == "0.1.0"
    assert EXTENSION_VERSION_TYPED_LDP == "0.2.0"
    assert "ldp" not in old_entry[0].schema["properties"]["metadata"].get(
        "properties", {}
    )
    assert "ldp" in typed_entry[0].schema["properties"]["metadata"]["properties"]


def test_pipeline_v01_delta_metadata_remains_roundtrip_only() -> None:
    from umf import Document

    from tablespec.extensions.umf import EXTENSION_ID, from_legacy, to_legacy

    legacy = {
        "table_name": "legacy_delta",
        "columns": [{"name": "record_id", "data_type": "VARCHAR"}],
        "source": {
            "kind": "delta",
            "table": "catalog.schema.events",
            "read_mode": "append_stream",
            "starting_version": 0,
            "identity_scope": {
                "enrollment_id": "legacy",
                "installation_id": "old-install",
                "destination_generation": "old-generation",
            },
        },
        "ldp": {"unrecognized_until_promoted": True},
    }
    promoted = from_legacy(legacy).to_dict()
    assert promoted["vocabularies"][EXTENSION_ID]["version"] == "0.2.0"
    promoted["vocabularies"][EXTENSION_ID]["version"] = "0.1.0"
    historical = Document.model_validate(promoted)
    with pytest.raises(ValueError, match="0.1.0 metadata remains opaque"):
        to_legacy(historical)
    assert (
        historical.to_dict()["modules"][0]["extensions"][EXTENSION_ID]["metadata"][
            "ldp"
        ]
        == legacy["ldp"]
    )


def test_publication_readiness_uses_current_version_and_fresh_fenced_lease() -> None:
    from tablespec.ldp.capability import capability_for_umf

    cap = capability_for_umf(_spec())
    ready = assess_publication_readiness("events", cap, _evidence())
    assert ready.status == "ready"
    assert ready.current_source_version == 14
    assert set(ready.dependencies) == set(_evidence().required_dependency_ids)
    assert ready.materialized_through == 121 and ready.projected_through == 120
    assert ready.writer_fence == "fence-17"

    stale_evidence = _evidence().model_copy(
        update={"writer_lease_expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}
    )
    stale = assess_publication_readiness("events", cap, stale_evidence)
    assert stale.status == "blocked"
    assert "WRITER_LEASE_STALE" in {issue.code for issue in stale.blockers}


def _wire_row(seq: int, revision: int, text: str, **scope_updates) -> dict:
    from tablespec.ldp.capability import capability_for_umf

    scope = capability_for_umf(_spec()).source.identity_scope.model_dump(mode="python")
    scope.update(scope_updates)
    encoded = json.dumps(
        {"seq": seq, "revision": revision, "text": text}, separators=(",", ":")
    )
    return {
        **scope,
        "delivery_seq": seq,
        "record_id": "record-A",
        "record_revision": revision,
        "record_kind": "record",
        "record_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "item_json": encoded,
        "payload": text,
    }


def test_execution_graph_scope_conflicts_replay_and_big_integer_revisions() -> None:
    from tablespec.ldp.capability import capability_for_umf

    cap = capability_for_umf(_spec())
    calls = []

    def validator(row, identity):
        calls.append(row["item_json"])
        assert all(row[key] == value for key, value in identity.items())
        return dict(row)

    def reconstruct(encoded):
        assert len(encoded) == 1
        return {
            "state": "complete",
            "payload_json": encoded[0],
            "record_sha256": hashlib.sha256(encoded[0].encode()).hexdigest(),
            "disposition": "upsert",
        }

    huge_revision = 2**53 + 7
    repeated = _wire_row(1, huge_revision, "same")
    conflict_a = _wire_row(2, huge_revision + 1, "a")
    conflict_b = _wire_row(2, huge_revision + 1, "b")
    out_of_scope = _wire_row(3, 1, "skip", enrollment_id="other")
    result = execute_revision_graph(
        [repeated, dict(repeated), conflict_a, conflict_b, out_of_scope],
        cap,
        validate_item=validator,
        reconstruct_revision=reconstruct,
    )
    assert len(calls) == 4
    assert len(result.validated_items) == 4
    assert len(result.conflicts) == 1
    assert result.conflicts[0]["code"] == "DELIVERY_SEQUENCE_CONFLICT"
    assert len(result.conflicts[0]["canonical_item_sha256"]) == 2
    assert len(result.revision_facts) == 1
    assert result.revision_facts[0]["record_revision"] == huge_revision
    assert result.latest[0]["record_revision"] == huge_revision


def test_execution_graph_persists_pending_and_bounds_before_transform() -> None:
    from tablespec.ldp.capability import capability_for_umf

    cap = capability_for_umf(_spec())
    first = _wire_row(10, 4, "partial")
    second = _wire_row(11, 4, "next")
    calls = []

    def validator(row, identity):
        return dict(row)

    def pending(encoded):
        calls.append(len(encoded))
        return {
            "state": "pending",
            "payload_json": None,
            "record_sha256": None,
            "disposition": None,
        }

    result = execute_revision_graph(
        [first], cap, validate_item=validator, reconstruct_revision=pending
    )
    assert result.pending_items == (first,)
    assert not result.revision_facts
    completed = execute_revision_graph(
        [second],
        cap,
        validate_item=validator,
        reconstruct_revision=lambda encoded: {
            "state": "complete",
            "payload_json": "joined",
            "record_sha256": HASH,
            "disposition": "upsert",
        },
        prior_pending=result.pending_items,
    )
    assert completed.revision_facts[0]["record_revision"] == 4

    declaration = cap.model_dump(mode="python")
    declaration["transform"]["max_group_items"] = 1
    limited = type(cap).model_validate(declaration)
    oversized = execute_revision_graph(
        [first, second], limited, validate_item=validator, reconstruct_revision=pending
    )
    assert oversized.conflicts[0]["code"] == "REVISION_GROUP_LIMIT"
    assert calls == [1]


def test_execution_graph_normalizes_spark_row_before_typed_validator() -> None:
    from tablespec.ldp.capability import capability_for_umf

    cap = capability_for_umf(_spec())
    row = _wire_row(1, 1, "row")

    class SparkLikeRow:
        def asDict(self, *, recursive: bool):
            assert recursive
            return row

    result = execute_revision_graph(
        [SparkLikeRow()],
        cap,
        validate_item=lambda value, identity: dict(value),
        reconstruct_revision=lambda encoded: {
            "state": "complete",
            "payload_json": encoded[0],
            "record_sha256": HASH,
            "disposition": "upsert",
        },
    )
    assert len(result.revision_facts) == 1
    assert as_row_mapping(SparkLikeRow()) == row


@pytest.mark.parametrize("with_prior_pending", [False, True])
def test_revision_processor_enforces_byte_bound_before_buffering_rows(
    monkeypatch, with_prior_pending: bool
) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyspark.sql.streaming.stateful_processor")

    from tablespec.ldp import artifact_runtime, stateful
    from tablespec.ldp.capability import capability_for_umf

    capability = capability_for_umf(_spec())
    previous = _wire_row(1, 2, "prior-pending")
    incoming = _wire_row(2, 2, "incoming-over-limit")
    later = _wire_row(3, 2, "later-over-limit")
    for item in (previous, incoming, later):
        item["delivery_sequence"] = item.pop("delivery_seq")
        item["content_hash"] = item["record_sha256"]
    previous_size = len(previous["item_json"].encode("utf-8"))
    incoming_size = len(incoming["item_json"].encode("utf-8"))
    later_size = len(later["item_json"].encode("utf-8"))
    max_bytes = (
        previous_size + incoming_size + later_size - 1
        if with_prior_pending
        else incoming_size - 1
    )
    transform = capability.transform.model_copy(update={"max_group_bytes": max_bytes})
    capability = capability.model_copy(update={"transform": transform})

    monkeypatch.setattr(
        artifact_runtime,
        "load_pinned_callable",
        lambda *_args: lambda _encoded: pytest.fail("overflow must precede codec call"),
    )
    monkeypatch.setattr(
        artifact_runtime,
        "load_pinned_schema",
        lambda binding: (
            {"type": "array", "items": {"type": "string"}}
            if binding.schema_id.endswith("reconstruction-input:1.0.0")
            else {"type": "object"}
        ),
    )
    monkeypatch.setattr(stateful, "_declared_rejection_types", lambda *_args: ())

    class FakeValueState:
        def __init__(self):
            self.value = None

        def get(self):
            return self.value

        def update(self, value):
            self.value = value

    class FakeHandle:
        def __init__(self):
            self.value_state = FakeValueState()

        def getValueState(self, *_args):
            return self.value_state

    handle = FakeHandle()
    frames = [pd.DataFrame([incoming])]
    if with_prior_pending:
        handle.value_state.value = (
            "pending",
            json.dumps({"1": previous["item_json"]}),
            None,
            1,
        )
        frames = [pd.DataFrame([incoming]), pd.DataFrame([later])]
    processor = stateful.make_revision_processor(capability)
    processor.init(handle)

    output = list(
        processor.handleInputRows(("scope", "record-A", 2), iter(frames), None)
    )
    assert handle.value_state.value[0] == "conflict"
    assert output
    assert output[0].iloc[0]["reason_code"] == "REVISION_GROUP_LIMIT"
    assert len(handle.value_state.value[1].encode("utf-8")) <= max_bytes + 32
