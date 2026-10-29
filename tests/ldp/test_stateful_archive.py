from __future__ import annotations

import pytest

from tablespec.ldp.stateful import (
    _event_frame,
    _exact_protocol_integer,
    _declared_rejection_types,
    _RowRejected,
    revision_transition,
    sequence_transition,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _item(seq: int, revision: int, text: str) -> dict:
    import json

    return {
        "enrollment_id": "qualification",
        "installation_id": "install-a",
        "destination_generation": "gen-1",
        "delivery_sequence": seq,
        "record_id": "record-a",
        "record_revision": revision,
        "content_hash": "hash-" + text,
        "item_json": json.dumps(
            {
                "delivery_seq": seq,
                "record_id": "record-a",
                "record_revision": revision,
                "record_kind": "event",
                "record_sha256": "a" * 64,
                "payload_json": text,
            },
            separators=(",", ":"),
        ),
        "wire_json": "{}",
    }


def test_same_sequence_replay_is_suppressed_then_conflict_is_appended() -> None:
    first = _item(1, 1, "first")
    state, accepted = sequence_transition(None, [first], max_bytes=1024)
    assert [row["event_type"] for row in accepted] == ["accepted_item"]

    replay_state, replay_events = sequence_transition(state, [first], max_bytes=1024)
    assert replay_state == state
    assert replay_events == []

    conflict_state, conflicts = sequence_transition(
        state, [_item(1, 1, "different")], max_bytes=1024
    )
    assert conflict_state["status"] == "conflict"
    assert conflicts[0]["reason_code"] == "DELIVERY_SEQUENCE_CONFLICT"
    assert (
        len(
            __import__("json").loads(conflicts[0]["evidence_json"])[
                "canonical_item_sha256"
            ]
        )
        == 2
    )


def test_later_sequence_conflict_does_not_retract_previously_appended_fact() -> None:
    rows = []
    seq1 = _item(1, 1, "complete")
    seq_state, accepted = sequence_transition(None, [seq1], max_bytes=1024)
    assert accepted[0]["event_type"] == "accepted_item"

    def complete(items):
        return {
            "state": "complete",
            "payload_json": items[0],
            "record_sha256": "a" * 64,
            "disposition": "upsert",
        }

    revision_state, revision_events = revision_transition(
        None, accepted, reconstruct_revision=complete, max_items=4, max_bytes=1024
    )
    rows.extend(revision_events)
    assert rows[0]["event_type"] == "revision"
    exact_fact = dict(rows[0])

    _, replay = sequence_transition(seq_state, [seq1], max_bytes=1024)
    assert replay == []
    seq_state, later_conflict = sequence_transition(
        seq_state, [_item(1, 1, "conflict")], max_bytes=1024
    )
    rows.extend(later_conflict)
    assert rows[0] == exact_fact
    assert rows[0]["event_type"] == "revision"
    assert rows[1]["event_type"] == "conflict"
    assert revision_state["status"] == "complete"


def test_empty_conflicted_update_remains_an_explicit_durable_event() -> None:
    item_a, item_b = _item(7, 3, "a"), _item(7, 3, "b")
    state, events = sequence_transition(None, [item_a, item_b], max_bytes=1024)
    assert state["status"] == "conflict"
    assert events and events[0]["event_type"] == "conflict"
    assert not any(event["event_type"] == "accepted_item" for event in events)


def test_revision_pending_chunks_persist_and_bounds_precede_reconstruction() -> None:
    called = []

    def reconstruct(items):
        called.append(items)
        return {"state": "pending"}

    first = _item(2**53 + 1, 2**53 + 3, "chunk-a")
    pending_state, pending_events = revision_transition(
        None, [first], reconstruct_revision=reconstruct, max_items=2, max_bytes=1024
    )
    assert pending_state["status"] == "pending"
    assert pending_events[0]["event_type"] == "pending"
    assert called[0] == [first["item_json"]]

    overflow_state, overflow_events = revision_transition(
        pending_state,
        [_item(2**53 + 2, 2**53 + 3, "chunk-b")],
        reconstruct_revision=lambda _: pytest.fail(
            "over-limit groups must not call the codec"
        ),
        max_items=1,
        max_bytes=1024,
    )
    assert overflow_state["status"] == "conflict"
    assert overflow_events[0]["reason_code"] == "REVISION_GROUP_LIMIT"


def test_sequence_conflict_decision_is_bounded_for_large_input_group() -> None:
    def rows():
        yield _item(9, 1, "first")
        for index in range(100_000):
            yield _item(9, 1, f"different-{index}")

    state, events = sequence_transition(None, rows(), max_bytes=1024)
    assert state["status"] == "conflict"
    evidence = __import__("json").loads(events[0]["evidence_json"])
    assert len(evidence["canonical_item_sha256"]) == 2


def test_pandas_boundary_preserves_int64_with_nullable_output_columns() -> None:
    import pandas as pd
    import numpy as np

    large = 2**53 + 1
    sequence_event = _event_frame(
        pd, {"delivery_sequence": large, "record_revision": None, "event_order": 1}
    )
    revision_event = _event_frame(
        pd, {"delivery_sequence": None, "record_revision": large, "event_order": 2}
    )
    combined = pd.concat([sequence_event, revision_event], ignore_index=True)
    assert str(combined["delivery_sequence"].dtype) == "Int64"
    assert int(combined.loc[0, "delivery_sequence"]) == large
    assert pd.isna(combined.loc[1, "delivery_sequence"])
    assert int(combined.loc[1, "record_revision"]) == large
    assert _exact_protocol_integer(large, "record revision") == large
    assert _exact_protocol_integer(np.int64(large), "record revision") == large
    with pytest.raises(RuntimeError, match="exact BIGINT"):
        _exact_protocol_integer(float(large), "record revision")

    incoming = pd.DataFrame(
        {
            "delivery_seq": pd.array([large, None], dtype="Int64"),
            "record_revision": pd.array([large, 1], dtype="Int64"),
        }
    )
    rows = list(incoming.itertuples(index=False, name=None))
    assert _exact_protocol_integer(rows[0][0], "delivery sequence") == large
    with pytest.raises(_RowRejected, match="delivery sequence is null"):
        _exact_protocol_integer(rows[1][0], "delivery sequence")


def test_unavailable_declared_rejection_type_fails_closed_before_data_decision() -> (
    None
):
    from types import SimpleNamespace

    def validator():
        return None

    with pytest.raises(RuntimeError, match="not available in the pinned closure"):
        _declared_rejection_types(
            validator,
            SimpleNamespace(data_rejection_exceptions=["MissingRejectedItem"]),
        )


def test_unexpected_reconstructor_failure_propagates_instead_of_becoming_conflict() -> (
    None
):
    with pytest.raises(RuntimeError, match="deployment failure"):
        revision_transition(
            None,
            [_item(1, 1, "x")],
            reconstruct_revision=lambda _: (_ for _ in ()).throw(
                RuntimeError("deployment failure")
            ),
            max_items=4,
            max_bytes=1024,
        )


def test_new_delivery_sequence_with_identical_inline_representation_is_idempotent() -> (
    None
):
    def complete(_):
        return {
            "state": "complete",
            "payload_json": "same",
            "record_sha256": "a" * 64,
            "disposition": "upsert",
        }

    first = _item(1, 1, "same")
    state, events = revision_transition(
        None, [first], reconstruct_revision=complete, max_items=4, max_bytes=1024
    )
    assert [event["event_type"] for event in events] == ["revision"]
    alias = _item(2, 1, "same")
    after_alias, alias_events = revision_transition(
        state, [alias], reconstruct_revision=complete, max_items=4, max_bytes=1024
    )
    assert alias_events == []
    assert after_alias["status"] == "complete"
    assert __import__("json").loads(after_alias["fact_json"])["delivery_count"] == 2

    changed = _item(3, 1, "changed")
    conflicted, conflict_events = revision_transition(
        after_alias,
        [changed],
        reconstruct_revision=complete,
        max_items=4,
        max_bytes=1024,
    )
    assert conflicted["status"] == "conflict"
    assert conflict_events[0]["reason_code"] == "IMMUTABLE_REVISION_CONFLICT"


def test_new_delivery_sequence_chunk_alias_requires_same_per_index_hash() -> None:
    def chunk(seq: int, digest: str) -> dict:
        wire = {
            "delivery_seq": seq,
            "record_id": "record-a",
            "record_revision": 1,
            "record_kind": "event",
            "record_sha256": "a" * 64,
            "chunk_index": 0,
            "chunk_count": 1,
            "record_bytes": 1,
            "chunk_sha256": digest,
            "chunk_base64": "eA==",
        }
        return {
            **_item(seq, 1, str(seq)),
            "content_hash": "a" * 64,
            "item_json": __import__("json").dumps(
                wire, sort_keys=True, separators=(",", ":")
            ),
        }

    def complete(_):
        return {
            "state": "complete",
            "payload_json": "x",
            "record_sha256": "a" * 64,
            "disposition": "upsert",
        }

    first = chunk(1, "b" * 64)
    state, events = revision_transition(
        None, [first], reconstruct_revision=complete, max_items=4, max_bytes=1024
    )
    assert events[0]["event_type"] == "revision"
    same_alias = chunk(2, "b" * 64)
    state, events = revision_transition(
        state, [same_alias], reconstruct_revision=complete, max_items=4, max_bytes=1024
    )
    assert state["status"] == "complete" and events == []
    forged_alias = chunk(3, "c" * 64)
    state, events = revision_transition(
        state,
        [forged_alias],
        reconstruct_revision=complete,
        max_items=4,
        max_bytes=1024,
    )
    assert state["status"] == "conflict"
    assert events[0]["reason_code"] == "IMMUTABLE_REVISION_CONFLICT"
