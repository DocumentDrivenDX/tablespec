# SPDX-License-Identifier: MIT OR Apache-2.0
"""Stateful, append-only LDP processors for scoped revision archives.

The processor factories are called only by generated PySpark pipeline modules.
They deliberately keep sequence and revision state in Structured Streaming's
checkpoint and emit facts/conflicts as append events. No watermark or TTL is set.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from hashlib import sha256
import json
from numbers import Integral
from typing import Any

from tablespec.ldp.capability import LdpCapability


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _item_representation(item_json: str) -> dict[str, Any]:
    item = json.loads(item_json)
    common = {
        "record_kind": item.get("record_kind"),
        "record_sha256": item.get("record_sha256"),
    }
    if "payload_json" in item:
        common.update(
            kind="inline",
            payload_sha256=_digest(item["payload_json"]),
        )
    else:
        common.update(
            kind="chunk",
            chunk_count=item.get("chunk_count"),
            record_bytes=item.get("record_bytes"),
            chunk_index=item.get("chunk_index"),
            chunk_sha256=item.get("chunk_sha256"),
        )
    return common


def _revision_representation(item_json_values: Iterable[str]) -> dict[str, Any]:
    items = [_item_representation(value) for value in item_json_values]
    if not items:
        raise ValueError("a completed revision must have validated delivery items")
    first = items[0]
    if first["kind"] == "inline":
        if any(item != first for item in items):
            raise ValueError(
                "inline items do not describe one immutable representation"
            )
        return first
    manifest = {
        key: first[key]
        for key in (
            "kind",
            "record_kind",
            "record_sha256",
            "chunk_count",
            "record_bytes",
        )
    }
    chunks: dict[str, str] = {}
    for item in items:
        if any(item.get(key) != value for key, value in manifest.items()):
            raise ValueError("chunk items do not share one immutable manifest")
        index = item["chunk_index"]
        index_key = str(index)
        previous = chunks.get(index_key)
        if previous is not None and previous != item["chunk_sha256"]:
            raise ValueError("chunk index has conflicting content")
        chunks[index_key] = item["chunk_sha256"]
    if len(chunks) != manifest["chunk_count"] or set(chunks) != {
        str(i) for i in range(manifest["chunk_count"])
    }:
        raise ValueError("completed revision does not retain a complete chunk manifest")
    return {**manifest, "chunks": chunks}


def _same_representation(manifest: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    if manifest.get("kind") != item.get("kind"):
        return False
    if manifest.get("record_kind") != item.get("record_kind") or manifest.get(
        "record_sha256"
    ) != item.get("record_sha256"):
        return False
    if item.get("kind") == "inline":
        return manifest.get("payload_sha256") == item.get("payload_sha256")
    index = item.get("chunk_index")
    return (
        manifest.get("chunk_count") == item.get("chunk_count")
        and manifest.get("record_bytes") == item.get("record_bytes")
        and manifest.get("chunks", {}).get(str(index)) == item.get("chunk_sha256")
    )


def _archive_event(scope: Mapping[str, Any], **values: Any) -> dict[str, Any]:
    return {
        **dict(scope),
        "event_type": None,
        "delivery_sequence": None,
        "record_id": None,
        "record_revision": None,
        "content_hash": None,
        "payload_json": None,
        "record_sha256": None,
        "disposition": None,
        "reason_code": None,
        "evidence_json": None,
        "event_order": 0,
        "item_json": None,
        "wire_json": None,
        **values,
    }


def _event_frame(pd, event: Mapping[str, Any]):
    """Build nullable BIGINT columns without pandas float coercion."""
    integer_columns = {"delivery_sequence", "record_revision", "event_order"}
    columns = {}
    for name, value in event.items():
        if name in integer_columns:
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, Integral)
            ):
                raise TypeError(
                    f"{name} must remain an exact integer through the pandas boundary"
                )
            columns[name] = pd.array(
                [None if value is None else int(value)], dtype="Int64"
            )
        else:
            columns[name] = [value]
    return pd.DataFrame(columns)


def _exact_protocol_integer(value: Any, name: str) -> int:
    if value is None or value.__class__.__name__ == "NAType":
        raise _RowRejected(f"{name} is null")
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise RuntimeError(
            f"{name} lost exact BIGINT representation at pandas boundary"
        )
    return int(value)


class _RowRejected(Exception):
    """A bounded, expected source-row rejection that can be archived."""


def _declared_rejection_types(function, stage):
    """Resolve only exception classes explicitly named by the stage binding."""
    namespace = getattr(function, "__globals__", {})
    resolved = []
    for name in stage.data_rejection_exceptions:
        value = namespace.get(name)
        if not isinstance(value, type) or not issubclass(value, Exception):
            raise RuntimeError(
                "declared adapter rejection exception is not available in the pinned closure"
            )
        resolved.append(value)
    return tuple(resolved)


def sequence_transition(
    prior: Mapping[str, Any] | None,
    items: Iterable[Mapping[str, Any]],
    *,
    max_bytes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure exact-byte decision for one scoped delivery sequence."""
    candidate: dict[str, Any] | None = None
    candidate_bytes: bytes | None = None
    conflicting_hashes: set[str] = set()
    oversized = False
    for item in items:
        encoded = item["item_json"].encode("utf-8")
        if len(encoded) > max_bytes:
            oversized = True
            if len(conflicting_hashes) < 2:
                conflicting_hashes.add(_digest(encoded.decode("utf-8")))
            continue
        if candidate_bytes is None:
            candidate_bytes = encoded
            candidate = dict(item)
        elif candidate_bytes != encoded:
            if len(conflicting_hashes) < 2:
                conflicting_hashes.add(_digest(candidate_bytes.decode("utf-8")))
            if len(conflicting_hashes) < 2:
                conflicting_hashes.add(_digest(encoded.decode("utf-8")))

    if prior and prior.get("status") == "conflict":
        return dict(prior), []

    existing = prior.get("item_json") if prior else None
    if oversized:
        next_state = {"status": "conflict", "item_json": existing, "wire_json": None}
        return next_state, [
            {
                "event_type": "conflict",
                "reason_code": "ITEM_LIMIT",
                "evidence_json": json.dumps(
                    {"canonical_item_sha256": sorted(conflicting_hashes)},
                    sort_keys=True,
                ),
            }
        ]

    if len(conflicting_hashes) > 1:
        next_state = {"status": "conflict", "item_json": existing, "wire_json": None}
        return next_state, [
            {
                "event_type": "conflict",
                "reason_code": "DELIVERY_SEQUENCE_CONFLICT",
                "evidence_json": json.dumps(
                    {"canonical_item_sha256": sorted(conflicting_hashes)},
                    sort_keys=True,
                ),
            }
        ]

    if candidate is None or candidate_bytes is None:
        return dict(
            prior or {"status": "empty", "item_json": None, "wire_json": None}
        ), []

    item_json = candidate_bytes.decode("utf-8")
    if existing is not None:
        if existing == item_json:
            return dict(
                prior
                or {"status": "accepted", "item_json": existing, "wire_json": None}
            ), []
        hashes = sorted({_digest(existing), _digest(item_json)})
        next_state = {"status": "conflict", "item_json": existing, "wire_json": None}
        return next_state, [
            {
                "event_type": "conflict",
                "reason_code": "DELIVERY_SEQUENCE_CONFLICT",
                "evidence_json": json.dumps(
                    {"canonical_item_sha256": hashes}, sort_keys=True
                ),
            }
        ]

    next_state = {
        "status": "accepted",
        "item_json": item_json,
        "wire_json": candidate["wire_json"],
    }
    return next_state, [{"event_type": "accepted_item", **candidate}]


def revision_transition(
    prior: Mapping[str, Any] | None,
    items: Iterable[Mapping[str, Any]],
    *,
    reconstruct_revision: Callable[[Sequence[str]], Mapping[str, Any]],
    max_items: int,
    max_bytes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure bounded revision-state transition; emits a fact at most once."""
    state = dict(prior or {"status": "pending", "items": {}, "event_order": 0})
    existing_items = dict(state.get("items") or {})
    events: list[dict[str, Any]] = []
    for item in items:
        sequence = item["delivery_sequence"]
        item_json = item["item_json"]
        old = existing_items.get(str(sequence))
        if old is not None:
            if old != item_json:
                state["status"] = "conflict"
                events.append(
                    {
                        "event_type": "conflict",
                        "reason_code": "DELIVERY_SEQUENCE_CONFLICT",
                    }
                )
            continue
        if state.get("status") == "conflict":
            continue
        if state.get("status") in {"complete", "replay_check"}:
            fact = json.loads(state.get("fact_json") or "{}")
            representation = _item_representation(item_json)
            size = len(item_json.encode("utf-8"))
            next_count = int(fact.get("delivery_count", 0)) + 1
            next_bytes = int(fact.get("delivery_bytes", 0)) + size
            if next_count > max_items or next_bytes > max_bytes:
                state["status"] = "conflict"
                events.append(
                    {"event_type": "conflict", "reason_code": "REVISION_GROUP_LIMIT"}
                )
                continue
            if not _same_representation(fact.get("representation", {}), representation):
                state["status"] = "conflict"
                events.append(
                    {
                        "event_type": "conflict",
                        "reason_code": "IMMUTABLE_REVISION_CONFLICT",
                    }
                )
                continue
            fact["delivery_count"] = next_count
            fact["delivery_bytes"] = next_bytes
            state["fact_json"] = json.dumps(fact, sort_keys=True, separators=(",", ":"))
            state["status"] = "complete"
            continue
        if len(existing_items) >= max_items:
            state["status"] = "conflict"
            events.append(
                {"event_type": "conflict", "reason_code": "REVISION_GROUP_LIMIT"}
            )
            continue
        item_bytes = item_json.encode("utf-8")
        current_bytes = sum(
            len(value.encode("utf-8")) for value in existing_items.values()
        )
        if current_bytes + len(item_bytes) > max_bytes:
            state["status"] = "conflict"
            events.append(
                {"event_type": "conflict", "reason_code": "REVISION_GROUP_LIMIT"}
            )
            continue
        proposed = {**existing_items, str(sequence): item_json}
        existing_items = proposed
        ordered = [existing_items[key] for key in sorted(existing_items, key=int)]
        result = reconstruct_revision(ordered)
        state["event_order"] = int(state.get("event_order", 0)) + 1
        state["items"] = existing_items
        if result.get("state") == "pending":
            if (
                state.get("status") == "complete"
                or state.get("status") == "replay_check"
            ):
                state["status"] = "replay_check"
            else:
                state["status"] = "pending"
                events.append(
                    {"event_type": "pending", "event_order": state["event_order"]}
                )
        elif result.get("state") == "complete":
            representation = _revision_representation(existing_items.values())
            if result.get("record_sha256") != representation.get("record_sha256"):
                state["status"] = "conflict"
                events.append(
                    {
                        "event_type": "conflict",
                        "event_order": state["event_order"],
                        "reason_code": "IMMUTABLE_REVISION_CONFLICT",
                    }
                )
            else:
                state["status"] = "complete"
                state["fact_json"] = json.dumps(
                    {
                        "record_sha256": result.get("record_sha256"),
                        "representation": representation,
                        "delivery_count": len(existing_items),
                        "delivery_bytes": sum(
                            len(value.encode("utf-8"))
                            for value in existing_items.values()
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                events.append(
                    {
                        "event_type": "revision",
                        "event_order": state["event_order"],
                        **dict(result),
                    }
                )
        else:
            state["status"] = "conflict"
            events.append(
                {
                    "event_type": "conflict",
                    "event_order": state["event_order"],
                    "reason_code": "RECONSTRUCTION_CONFLICT",
                }
            )
    state["items"] = existing_items
    return state, events


def make_sequence_processor(capability: LdpCapability):
    """Build a checkpoint-backed PySpark processor for exact delivery identity."""
    import pandas as pd
    from pyspark.sql.streaming.stateful_processor import StatefulProcessor

    from tablespec.ldp.artifact_runtime import load_pinned_callable, load_pinned_schema

    class SequenceDecisionProcessor(StatefulProcessor):
        def __init__(self):
            self._capability = capability

        def init(self, handle):
            self._state = handle.getValueState(
                "delivery-sequence-v1",
                "status string, item_json string, wire_json string",
            )
            self._stage = next(
                s
                for s in self._capability.transform.stages
                if s.role == "validate_raw_item"
            )
            self._validator = load_pinned_callable(
                self._capability.transform, self._stage.entrypoint
            )
            self._rejection_types = _declared_rejection_types(
                self._validator, self._stage
            )
            self._input_schema = load_pinned_schema(self._stage.input)
            self._output_schema = load_pinned_schema(self._stage.output)

        def handleInputRows(self, key, rows, timerValues):
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import ValidationError

            current = self._state.get()
            prior = (
                None
                if current is None
                else {
                    "status": current[0],
                    "item_json": current[1],
                    "wire_json": current[2],
                }
            )
            invalid = False

            def validated_items():
                nonlocal invalid
                for frame in rows:
                    if any(
                        str(frame[name].dtype).lower().startswith("float")
                        for name in (
                            self._capability.revisions.delivery_sequence,
                            self._capability.revisions.record_revision,
                        )
                    ):
                        raise RuntimeError(
                            "protocol BIGINT column was coerced to floating point at pandas boundary"
                        )
                    for values in frame.itertuples(index=False, name=None):
                        raw = dict(zip(frame.columns, values, strict=True))
                        try:
                            args = {
                                "row": raw,
                                "identity": self._capability.source.identity_scope.model_dump(
                                    mode="python"
                                ),
                            }
                            policy = self._capability.revisions
                            for name in (
                                policy.delivery_sequence,
                                policy.record_revision,
                            ):
                                raw[name] = _exact_protocol_integer(raw.get(name), name)
                            Draft202012Validator(self._input_schema).validate(args)
                            wire = self._validator(raw, args["identity"])
                            Draft202012Validator(self._output_schema).validate(wire)
                            if any(
                                raw.get(k) != v for k, v in args["identity"].items()
                            ):
                                raise _RowRejected("scope mismatch")
                            if wire.get(policy.delivery_sequence) != raw.get(
                                policy.delivery_sequence
                            ):
                                raise _RowRejected("delivery sequence mismatch")
                            if wire.get(policy.record_id) != raw.get(policy.record_id):
                                raise _RowRejected("record identity mismatch")
                            if wire.get(policy.record_revision) != raw.get(
                                policy.record_revision
                            ):
                                raise _RowRejected("revision identity mismatch")
                            if wire.get(policy.record_kind) != raw.get(
                                policy.record_kind
                            ):
                                raise _RowRejected("record kind mismatch")
                            if wire.get(policy.content_hash) != raw.get(
                                policy.content_hash
                            ):
                                raise _RowRejected("content hash mismatch")
                            item_json = raw.get("item_json")
                            if not isinstance(item_json, str):
                                raise _RowRejected("canonical bytes are missing")
                            yield {
                                **{
                                    k: raw[k]
                                    for k in self._capability.archive.identity_fields
                                },
                                "delivery_sequence": raw[policy.delivery_sequence],
                                "record_id": wire[policy.record_id],
                                "record_revision": wire[policy.record_revision],
                                "content_hash": wire[policy.content_hash],
                                "item_json": item_json,
                                "wire_json": json.dumps(
                                    wire,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                            }
                        except (ValidationError, _RowRejected, *self._rejection_types):
                            invalid = True

            next_state, events = sequence_transition(
                prior,
                validated_items(),
                max_bytes=self._capability.transform.max_group_bytes,
            )
            if invalid:
                next_state = {
                    "status": "conflict",
                    "item_json": prior.get("item_json") if prior else None,
                    "wire_json": None,
                }
                events = [
                    {
                        "event_type": "conflict",
                        "reason_code": "VALIDATION_REJECTED",
                        "evidence_json": "{}",
                    }
                ]
            self._state.update(
                (
                    next_state["status"],
                    next_state.get("item_json"),
                    next_state.get("wire_json"),
                )
            )
            for event in events:
                if event["event_type"] == "accepted_item":
                    yield _event_frame(
                        pd,
                        _archive_event(
                            {
                                k: event[k]
                                for k in self._capability.archive.identity_fields
                            },
                            event_type="accepted_item",
                            delivery_sequence=int(event["delivery_sequence"]),
                            record_id=event["record_id"],
                            record_revision=int(event["record_revision"]),
                            content_hash=event["content_hash"],
                            item_json=event["item_json"],
                            wire_json=event["wire_json"],
                        ),
                    )
                else:
                    scope = {
                        k: key[i]
                        for i, k in enumerate(self._capability.archive.identity_fields)
                    }
                    yield _event_frame(
                        pd,
                        _archive_event(
                            scope,
                            event_type="conflict",
                            delivery_sequence=key[-1],
                            reason_code=event["reason_code"],
                            evidence_json=event["evidence_json"],
                            event_order=1,
                        ),
                    )

        def close(self):
            return None

    return SequenceDecisionProcessor()


def make_revision_processor(capability: LdpCapability):
    """Build a checkpoint-backed bounded revision reconstructor."""
    import pandas as pd
    from pyspark.sql.streaming.stateful_processor import StatefulProcessor

    from tablespec.ldp.artifact_runtime import load_pinned_callable, load_pinned_schema

    class RevisionArchiveProcessor(StatefulProcessor):
        def __init__(self):
            self._capability = capability

        def init(self, handle):
            self._state = handle.getValueState(
                "revision-archive-v1",
                "status string, items_json string, fact_json string, event_order long",
            )
            self._stage = next(
                s
                for s in self._capability.transform.stages
                if s.role == "reconstruct_revision"
            )
            self._reconstruct = load_pinned_callable(
                self._capability.transform, self._stage.entrypoint
            )
            self._rejection_types = _declared_rejection_types(
                self._reconstruct, self._stage
            )
            self._input_schema = load_pinned_schema(self._stage.input)
            self._output_schema = load_pinned_schema(self._stage.output)

        def handleInputRows(self, key, rows, timerValues):
            from jsonschema import Draft202012Validator

            current = self._state.get()
            prior = (
                None
                if current is None
                else {
                    "status": current[0],
                    "items": json.loads(current[1] or "{}"),
                    "fact_json": current[2],
                    "event_order": current[3] or 0,
                }
            )
            received = []
            overflow = False
            event_context = None
            failure_context = None
            batch_bytes = 0
            max_items = self._capability.transform.max_group_items
            max_bytes = self._capability.transform.max_group_bytes
            fact = json.loads(prior.get("fact_json") or "{}") if prior else {}
            if prior and prior.get("status") in {"complete", "replay_check"}:
                received_count = int(fact.get("delivery_count", 0))
                received_bytes = int(fact.get("delivery_bytes", 0))
            else:
                prior_items = prior.get("items", {}) if prior else {}
                received_count = len(prior_items)
                received_bytes = sum(
                    len(str(value).encode("utf-8")) for value in prior_items.values()
                )
            for frame in rows:
                for values in frame.itertuples(index=False, name=None):
                    if overflow:
                        continue
                    item = dict(zip(frame.columns, values, strict=True))
                    sequence = item.get("delivery_sequence")
                    item["delivery_sequence"] = _exact_protocol_integer(
                        sequence, "delivery sequence"
                    )
                    revision = item.get("record_revision")
                    item["record_revision"] = _exact_protocol_integer(
                        revision, "record revision"
                    )
                    if event_context is None:
                        event_context = {
                            name: item.get(name)
                            for name in (
                                *self._capability.archive.identity_fields,
                                "delivery_sequence",
                                "record_id",
                                "record_revision",
                                "content_hash",
                            )
                        }
                    item_json = item.get("item_json")
                    if not isinstance(item_json, str):
                        raise TypeError(
                            "item_json must be text before bounded state buffering"
                        )
                    item_size = len(item_json.encode("utf-8"))
                    if (
                        received_count + len(received) >= max_items
                        or received_bytes + batch_bytes + item_size > max_bytes
                    ):
                        overflow = True
                        failure_context = {
                            name: item.get(name)
                            for name in (
                                *self._capability.archive.identity_fields,
                                "delivery_sequence",
                                "record_id",
                                "record_revision",
                                "content_hash",
                            )
                        }
                        continue
                    received.append(item)
                    batch_bytes += item_size
            received.sort(key=lambda item: item["delivery_sequence"])

            def reconstruct(encoded):
                Draft202012Validator(self._input_schema).validate(encoded)
                try:
                    result = self._reconstruct(encoded)
                except self._rejection_types:
                    return {"state": "conflict"}
                Draft202012Validator(self._output_schema).validate(result)
                return result

            if overflow:
                next_state = dict(
                    prior or {"status": "pending", "items": {}, "event_order": 0}
                )
                next_state["status"] = "conflict"
                events = [
                    {"event_type": "conflict", "reason_code": "REVISION_GROUP_LIMIT"}
                ]
            else:
                next_state, events = revision_transition(
                    prior,
                    received,
                    reconstruct_revision=reconstruct,
                    max_items=self._capability.transform.max_group_items,
                    max_bytes=self._capability.transform.max_group_bytes,
                )

            if next_state.get("status") == "complete":
                # The durable archive owns payload retention after completion.
                next_state["items"] = {}
            self._state.update(
                (
                    next_state.get("status"),
                    json.dumps(
                        next_state.get("items", {}),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    next_state.get("fact_json"),
                    next_state.get("event_order", 0),
                )
            )
            for event in events:
                context = failure_context or (
                    received[0] if received else event_context
                )
                if context is None:
                    raise RuntimeError(
                        "state transition emitted evidence without row identity"
                    )
                delivery_sequence = _exact_protocol_integer(
                    context.get("delivery_sequence"), "delivery sequence"
                )
                record_revision = _exact_protocol_integer(
                    context.get("record_revision"), "record revision"
                )
                record_id = context.get("record_id")
                content_hash = context.get("content_hash")
                if not isinstance(record_id, str) or not isinstance(content_hash, str):
                    raise TypeError("archive event identity must remain textual")
                result = event if event.get("event_type") == "revision" else {}
                yield _event_frame(
                    pd,
                    _archive_event(
                        {
                            k: context[k]
                            for k in self._capability.archive.identity_fields
                        },
                        event_type=event["event_type"],
                        delivery_sequence=delivery_sequence,
                        record_id=record_id,
                        record_revision=record_revision,
                        content_hash=content_hash,
                        payload_json=result.get("payload_json"),
                        record_sha256=result.get("record_sha256"),
                        disposition=result.get("disposition"),
                        reason_code=event.get("reason_code"),
                        evidence_json="{}",
                        event_order=event.get("event_order", 0),
                    ),
                )

        def close(self):
            return None

    return RevisionArchiveProcessor()


__all__ = [
    "make_revision_processor",
    "make_sequence_processor",
    "revision_transition",
    "sequence_transition",
]
