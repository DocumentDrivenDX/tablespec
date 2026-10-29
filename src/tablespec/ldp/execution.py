# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bounded, side-effect-free LDP revision graph used by generated adapters.

This seam processes one already-pinned source snapshot/batch. Callers persist the
returned conflicts, pending items, immutable revision facts, and latest derivative
in their owning pipeline. It deliberately does not claim streaming-state durability
or a cross-table transaction.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from tablespec.ldp.capability import LdpCapability


@dataclass(frozen=True)
class RevisionGraphResult:
    validated_items: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    pending_items: tuple[dict[str, Any], ...]
    revision_facts: tuple[dict[str, Any], ...]
    latest: tuple[dict[str, Any], ...]


def as_row_mapping(row: Any) -> dict[str, Any]:
    """Normalize Spark ``Row`` and ordinary mappings at the adapter boundary."""
    if isinstance(row, Mapping):
        return dict(row)
    as_dict = getattr(row, "asDict", None)
    if callable(as_dict):
        result = as_dict(recursive=True)
        if isinstance(result, Mapping):
            return dict(result)
    raise TypeError("raw adapter input must be a mapping or Spark Row")


def _evidence(scope: Mapping[str, str], code: str, **fields: Any) -> dict[str, Any]:
    """Build redacted conflict evidence without source payload or exception text."""
    return {"identity_scope": dict(scope), "code": code, **fields}


def execute_revision_graph(
    rows: Iterable[Mapping[str, Any]],
    capability: LdpCapability,
    *,
    validate_item: Callable[[Mapping[str, Any], Mapping[str, str]], Mapping[str, Any]],
    reconstruct_revision: Callable[[Sequence[str]], Mapping[str, Any]],
    prior_pending: Iterable[Mapping[str, Any]] = (),
) -> RevisionGraphResult:
    """Validate, conflict-check, replay-collapse, bound, and reconstruct one batch.

    Scope filtering happens before adapter validation. Delivery conflicts are
    determined by exact canonical ``item_json`` bytes before replay collapse or
    revision grouping. The caller must persist ``pending_items`` and supply them
    again on the next source update; this function does not evict pending chunks.
    """
    scope = capability.source.identity_scope.model_dump(mode="python")
    policy = capability.revisions
    transform = capability.transform
    identity_fields = tuple(scope)
    sequence_field = policy.delivery_sequence
    revision_group = (*identity_fields, policy.record_id, policy.record_revision)
    conflicts: list[dict[str, Any]] = []
    validated: list[dict[str, Any]] = []

    for raw in rows:
        raw = as_row_mapping(raw)
        if any(raw.get(key) != value for key, value in scope.items()):
            continue
        try:
            item = validate_item(raw, scope)
            if not isinstance(item, Mapping):
                raise TypeError("validator result is not an object")
            item = dict(item)
            if any(raw.get(key) != value for key, value in scope.items()):
                raise ValueError("raw processing identity differs")
            if any(item.get(key) != raw.get(key) for key in (sequence_field, policy.content_hash)):
                raise ValueError("validated outer identity differs")
            # The validator's wire item intentionally does not contain the
            # processing-scope columns. Attach only the already-filtered,
            # declaration-bound values after validation.
            item.update(scope)
            if not isinstance(raw.get("item_json"), str):
                raise ValueError("canonical item bytes missing")
            sequence = item.get(sequence_field)
            revision = item.get(policy.record_revision)
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                raise ValueError("delivery sequence is not an integer")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError("record revision is not an integer")
            item["item_json"] = raw["item_json"]
            validated.append(item)
        except Exception:
            conflicts.append(_evidence(scope, "VALIDATION_REJECTED"))

    persisted_pending = []
    for old in prior_pending:
        item = as_row_mapping(old)
        if any(item.get(key) != value for key, value in scope.items()):
            continue
        if isinstance(item.get("item_json"), str):
            persisted_pending.append(item)
            validated.append(item)

    # Compare canonical bytes per scoped delivery sequence before exact replay
    # collapse. A conflicting sequence is excluded from every downstream stage.
    by_sequence: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in validated:
        key = (*[item[k] for k in identity_fields], item[sequence_field])
        by_sequence[key].append(item)
    conflicted_sequences: set[tuple[Any, ...]] = set()
    replay_collapsed: list[dict[str, Any]] = []
    for key, items in by_sequence.items():
        encoded = {item["item_json"].encode("utf-8") for item in items}
        if len(encoded) > 1:
            conflicted_sequences.add(key)
            conflicts.append(_evidence(
                scope,
                "DELIVERY_SEQUENCE_CONFLICT",
                delivery_sequence=key[-1],
                canonical_item_sha256=sorted(sha256(value).hexdigest() for value in encoded),
            ))
            continue
        replay_collapsed.append(items[0])

    # Partition by exact revision identity. The limits are checked before the
    # adapter receives a collection, so no unbounded list is passed to it.
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in replay_collapsed:
        groups[tuple(item[key] for key in revision_group)].append(item)
    for old in persisted_pending:
        groups[tuple(old[key] for key in revision_group)].append(old)

    pending: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for key, items in groups.items():
        # A sequence already conflicted in this batch remains blocked.
        if any((*[item[k] for k in identity_fields], item[sequence_field]) in conflicted_sequences for item in items):
            continue
        unique: dict[bytes, dict[str, Any]] = {}
        for item in items:
            unique.setdefault(item["item_json"].encode("utf-8"), item)
        ordered = sorted(unique.values(), key=lambda item: item[sequence_field])
        total_bytes = sum(len(item["item_json"].encode("utf-8")) for item in ordered)
        base = dict(zip(revision_group, key, strict=True))
        if len(ordered) > transform.max_group_items or total_bytes > transform.max_group_bytes:
            conflicts.append(_evidence(scope, "REVISION_GROUP_LIMIT", **base))
            continue
        result = reconstruct_revision([item["item_json"] for item in ordered])
        state = result.get("state")
        if state == "pending":
            pending.extend(ordered)
            continue
        if state != "complete":
            conflicts.append(_evidence(scope, "RECONSTRUCTION_CONFLICT", **base))
            continue
        facts.append({**base, **dict(result)})

    # Latest is a separate derivative; all revision facts remain intact above.
    latest_by_record: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fact in facts:
        key = (*[fact[k] for k in identity_fields], fact[policy.record_id])
        previous = latest_by_record.get(key)
        if previous is None or fact[policy.record_revision] > previous[policy.record_revision]:
            latest_by_record[key] = fact

    return RevisionGraphResult(
        validated_items=tuple(validated),
        conflicts=tuple(conflicts),
        pending_items=tuple(pending),
        revision_facts=tuple(facts),
        latest=tuple(latest_by_record.values()),
    )


__all__ = ["RevisionGraphResult", "as_row_mapping", "execute_revision_graph"]
