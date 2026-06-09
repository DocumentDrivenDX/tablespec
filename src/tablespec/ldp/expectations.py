"""Derive LDP EXPECTATIONS from UMF validation facts (PROTOTYPE).

Lakeflow Declarative Pipelines (LDP / the DLT rebrand) expresses data-quality
rules INLINE on a dataset as ``CONSTRAINT <name> EXPECT (<predicate>) ON VIOLATION
<action>``. This is the LDP analogue of the dbt ``schema.yml`` generic tests and
the Great-Expectations suite: instead of a post-hoc test, the constraint is part
of the streaming/materialized dataset definition and Databricks enforces it as
rows flow.

This module turns the SAME UMF facts the dbt emitter reads into neutral
:class:`LdpExpectation` value objects, then renders them as LDP constraint text:

  * ``nullable``  -> a ``not_null`` predicate (``<col> IS NOT NULL``). Primary-key
    columns are implicitly not-null.
  * ``primary_key`` / single-column ``unique_constraints`` -> noted as a uniqueness
    intent. LDP has no row-scoped UNIQUE expectation (uniqueness is global, not a
    per-row predicate), so this prototype emits it as a COMMENT, not a CONSTRAINT,
    and relies on ``APPLY CHANGES ... KEYS`` for primary-key dedup. This is an
    honest limitation, surfaced rather than faked.
  * ``expect_column_values_to_be_in_set`` -> an ``accepted_values`` predicate
    (``<col> IS NULL OR <col> IN (...)``; NULLs pass so the membership test is
    orthogonal to nullability, matching dbt's ``accepted_values``).
  * non-cross-pipeline foreign keys -> recorded as a relationship INTENT (a COMMENT)
    -- a referential-integrity check needs the parent dataset and is not a row-local
    predicate, so like uniqueness it is not a faithful single-dataset CONSTRAINT.

ON VIOLATION semantics come from the expectation's stage/severity/blocking meta
(:class:`~tablespec.models.umf.ExpectationMeta`) and the structural rules:

  * ``blocking: true`` -> ``FAIL UPDATE`` (the pipeline update aborts on any
    violation -- the LDP analogue of a blocking GX check / a dbt ``error`` test).
    Only a blocking check aborts; ``blocking`` is authoritative for aborting.
  * NOT blocking, ``severity in {critical, error, warning}`` -> ``DROP ROW``
    (quarantine the offending row; serious but non-aborting).
  * NOT blocking, ``severity: info`` / unset -> a WARN with NO ``ON VIOLATION``
    clause (keep the row, record only -- LDP's default/expect behaviour).

Structural not-null / accepted-values constraints derived from the schema (not an
expectation) default to ``FAIL UPDATE`` for a primary key / non-nullable column
(a typed pipeline must not silently admit nulls in a key) and ``DROP ROW`` for a
nullable column's domain enum.

Pure value derivation + text emission -- no dbt, no Spark, no Databricks import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from tablespec.core.schema_facts import accepted_values_tests, relationship_tests
from tablespec.expectation_utils import expectation_dicts_from_umf_data


class OnViolation(str, Enum):
    """LDP ``ON VIOLATION`` action for a constraint."""

    FAIL_UPDATE = "FAIL UPDATE"  # abort the pipeline update (blocking)
    DROP_ROW = "DROP ROW"  # quarantine the offending row (non-blocking)
    WARN = "WARN"  # record the metric, keep the row (no ON VIOLATION clause)


@dataclass(frozen=True)
class LdpExpectation:
    """One LDP constraint: a named boolean predicate + an ON VIOLATION action.

    Attributes:
        name: constraint identifier (``not_null_<col>`` / ``accepted_values_<col>``).
        predicate: the boolean SQL expression rows must satisfy.
        on_violation: the :class:`OnViolation` action.
    """

    name: str
    predicate: str
    on_violation: OnViolation

    def render(self) -> str:
        """Render the ``CONSTRAINT ... EXPECT (...) [ON VIOLATION ...]`` clause."""
        clause = f"CONSTRAINT {self.name} EXPECT ({self.predicate})"
        if self.on_violation is OnViolation.WARN:
            # LDP's default (record the metric, keep the row) is expressed by
            # OMITTING the ON VIOLATION clause.
            return clause
        return f"{clause} ON VIOLATION {self.on_violation.value}"


def _violation_action(meta: dict[str, Any]) -> OnViolation:
    """Map an expectation's meta to its LDP ``ON VIOLATION`` action.

    Precedence (``blocking`` caps how severe the action may be; severity then
    picks the non-aborting action):

      * ``blocking: true``  -> FAIL UPDATE (abort the update). ``blocking`` is
        authoritative for aborting: only a blocking check aborts the pipeline.
      * NOT blocking -> the check must NEVER abort, regardless of severity (a
        non-blocking ``error`` does not stop the pipeline). The action is then
        chosen by severity:
          - ``critical`` / ``error`` -> DROP ROW (quarantine the bad row; serious
            but non-aborting),
          - ``warning``              -> DROP ROW (quarantine),
          - ``info`` / unset         -> WARN (keep the row, record the metric only).

    (``blocking`` defaults to ``False`` in :class:`ExpectationMeta`, so an omitted
    flag is treated as non-blocking; raising severity to ``error`` strengthens the
    quarantine but never makes a non-blocking check abort.)
    """
    if meta.get("blocking") is True:
        return OnViolation.FAIL_UPDATE
    severity = meta.get("severity")
    if severity in {"critical", "error", "warning"}:
        return OnViolation.DROP_ROW
    return OnViolation.WARN


def _column_not_null(col: dict[str, Any], *, is_pk: bool) -> bool:
    """Resolve whether a column gets a not_null constraint.

    A primary-key column is always not-null. Otherwise mirror the core contract
    rule (``schema_facts._column_not_null``): not_null only when at least one
    context forbids null.
    """
    if is_pk:
        return True
    nullable = col.get("nullable")
    if nullable is None:
        return False
    if isinstance(nullable, bool):
        return not nullable
    if isinstance(nullable, dict):
        return not (all(nullable.values()) if nullable else True)
    return False


def _sql_literal(value: Any) -> str:
    """Render a value_set scalar as a SQL literal (type-faithful)."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def derive_expectations(umf_data: dict[str, Any]) -> list[LdpExpectation]:
    """Derive the renderable LDP CONSTRAINT expectations for a table.

    Covers the row-local predicates LDP can faithfully enforce on a SINGLE dataset:
    not_null (schema + PK) and accepted_values (domain enums). Uniqueness and FK
    relationships are intentionally NOT emitted as constraints here (they are not
    row-local); :func:`derive_comments` surfaces them as honest comments instead.

    The ON VIOLATION action for a structural not_null is FAIL UPDATE on a PK /
    non-nullable column. For a domain enum it is taken from the source
    expectation's blocking/severity meta when present, else DROP ROW.
    """
    pk: list[str] = umf_data.get("primary_key") or []
    pk_set = set(pk)
    out: list[LdpExpectation] = []

    # 1. not_null constraints from schema nullability + PK membership.
    for col in umf_data.get("columns") or []:
        name = col.get("name")
        if not name:
            continue
        if _column_not_null(col, is_pk=name in pk_set):
            out.append(
                LdpExpectation(
                    name=f"not_null_{name}",
                    predicate=f"{name} IS NOT NULL",
                    # A key / required column must not silently admit nulls in a
                    # typed pipeline -> abort the update.
                    on_violation=OnViolation.FAIL_UPDATE,
                )
            )

    # 2. accepted_values constraints from set-membership expectations. The
    #    blocking/severity meta of the originating expectation drives ON VIOLATION.
    meta_by_col = _accepted_values_meta(umf_data)
    for test in accepted_values_tests(umf_data):
        col = test.column
        values = test.values or ()
        in_list = ", ".join(_sql_literal(v) for v in values)
        # NULLs pass (membership is orthogonal to nullability -- mirrors dbt's
        # accepted_values, whose not-null is a separate test/constraint).
        predicate = f"{col} IS NULL OR {col} IN ({in_list})"
        meta = meta_by_col.get(col, {})
        on_violation = _violation_action(meta)
        out.append(
            LdpExpectation(
                name=f"accepted_values_{col}",
                predicate=predicate,
                on_violation=on_violation,
            )
        )

    return out


def _accepted_values_meta(umf_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map a column -> the meta dict of its in-set expectation (for ON VIOLATION).

    Reads the unified ``expectations.expectations`` suite first, then the legacy
    ``validation_rules.expectations`` GX list, so an expectation's blocking /
    severity drives the constraint action regardless of which field carries it.
    """
    by_col: dict[str, dict[str, Any]] = {}
    for exp in expectation_dicts_from_umf_data(umf_data):
        if exp.get("type") != "expect_column_values_to_be_in_set":
            continue
        col = (exp.get("kwargs") or {}).get("column")
        if col and col not in by_col:
            by_col[col] = exp.get("meta") or {}
    return by_col


def derive_comments(
    umf_data: dict[str, Any], resolve_target: Any, *, mode: str | None = None
) -> list[str]:
    """Honest notes for rules LDP cannot express as a single-dataset CONSTRAINT.

    Uniqueness (PK / unique_constraints) and FK relationships are global/parent-
    scoped, not row-local predicates, so this prototype does NOT fake them as
    constraints. It records them as comments so the generated SQL documents the
    intent and the gap is explicit. For an incremental+pk dataset the uniqueness is
    enforced by ``APPLY CHANGES ... KEYS``; for a snapshot / keyless dataset the
    note states the uniqueness is NOT enforced (a true LDP limitation), so the
    comment never overstates what the pipeline guarantees.

    Args:
        umf_data: UMF table data.
        resolve_target: ``resolve_target`` callback for FK relationship facts.
        mode: ingestion mode (``"incremental"`` / ``"snapshot"``) so the PK note
            reflects whether APPLY CHANGES actually dedups. ``None`` -> the generic
            "enforced for an incremental dataset" phrasing.
    """
    notes: list[str] = []
    pk: list[str] = umf_data.get("primary_key") or []
    if pk:
        if mode == "incremental":
            enforcement = (
                "is enforced by APPLY CHANGES ... KEYS (latest-per-key upsert)"
            )
        elif mode == "snapshot":
            enforcement = (
                "is NOT enforced by LDP (snapshot/full-reload dataset; LDP has no "
                "row-local UNIQUE expectation -- relies on the source being unique "
                "per key)"
            )
        else:
            enforcement = (
                "is enforced by APPLY CHANGES ... KEYS for an incremental dataset; "
                "LDP has no row-local UNIQUE expectation"
            )
        notes.append(
            f"-- uniqueness intent: PRIMARY KEY ({', '.join(pk)}) {enforcement}."
        )
    for uc in umf_data.get("unique_constraints") or []:
        cols = uc if isinstance(uc, list) else [uc]
        notes.append(
            f"-- uniqueness intent: UNIQUE ({', '.join(cols)}) (not row-local)."
        )
    for test in relationship_tests(umf_data, resolve_target):
        notes.append(
            f"-- relationship intent: {test.column} -> "
            f"{test.to_model}.{test.to_field} (referential integrity needs the "
            f"parent dataset; not a row-local EXPECT)."
        )
    return notes


__all__ = [
    "LdpExpectation",
    "OnViolation",
    "derive_comments",
    "derive_expectations",
]
