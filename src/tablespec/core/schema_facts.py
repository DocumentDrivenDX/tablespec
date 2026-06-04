"""Engine-agnostic derivation of per-column *schema test facts* from a UMF table.

This is the CORE seam that feeds the dbt ``schema.yml`` test emitter
(``tablespec.dbt.schema_tests``) WITHOUT any dbt knowledge living here. It turns
the two kinds of referential / domain facts a UMF carries into neutral value
objects:

  * :meth:`ColumnTest.relationship` -- a foreign-key edge ``column ->
    references_table.references_column`` (single-column; UMF ``ForeignKey`` is
    scalar and dbt-core ``relationships`` is single-column only).
  * :meth:`ColumnTest.accepted_values` -- a set-membership / domain enum, derived
    from an ``expect_column_values_to_be_in_set`` expectation's ``value_set``.

Resolving a FK's *target model name* is a backend concern (an ``ingested_<t>`` vs
``gold_<t>`` model name, or whether the target even exists in the rendered set),
so :func:`column_tests` takes a ``resolve_target`` callback. The core never
mentions ``ref()``/``ingested_``/``gold_`` -- it hands back the *logical*
referenced table and the resolver decides (returning ``None`` to SKIP an
unresolvable / external target, satisfying the "skip-when-unresolvable" rule).

Import rule (``tests/test_core_encapsulation.py``): nothing here imports
``tablespec.dbt``; this module is pure-Python value derivation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# An expectation of this type carries a domain enum in ``kwargs["value_set"]``.
_SET_MEMBERSHIP_TYPE = "expect_column_values_to_be_in_set"


@dataclass(frozen=True)
class ColumnTest:
    """One engine-agnostic schema test attached to a single column.

    ``kind`` is ``"relationship"`` or ``"accepted_values"``. The remaining fields
    are populated per kind; a backend renders this into its own test syntax.
    """

    column: str
    kind: str
    # relationship:
    to_model: str | None = None
    to_field: str | None = None
    # accepted_values: the original value_set scalars, preserving each element's
    # JSON/UMF type (int / float / bool / str). The backend renders types
    # faithfully -- an INTEGER domain emits an unquoted numeric set so the test
    # compares like-typed values against the warehouse column.
    values: tuple[Any, ...] | None = None

    @classmethod
    def relationship(cls, column: str, *, to_model: str, to_field: str) -> ColumnTest:
        """A referential-integrity edge from *column* to ``to_model.to_field``."""
        return cls(
            column=column,
            kind="relationship",
            to_model=to_model,
            to_field=to_field,
        )

    @classmethod
    def accepted_values(cls, column: str, *, values: list[Any]) -> ColumnTest:
        """A set-membership/domain enum: *column* values must be in ``values``.

        The element types are preserved (not coerced to ``str``) so an INTEGER
        domain like ``[1, 2, 3]`` round-trips as numbers; the backend decides how
        to render each scalar for its dialect.
        """
        return cls(
            column=column,
            kind="accepted_values",
            values=tuple(values),
        )


# A backend supplies this to resolve a *logical* referenced table name into the
# concrete model name it will emit (e.g. ``ingested_member`` / ``gold_x``), or
# ``None`` when the target is not in the rendered set (skip the test).
ResolveTarget = Callable[[str], str | None]


@dataclass(frozen=True)
class ColumnContract:
    """An engine-agnostic *data contract* for one column.

    This is the neutral value object a backend turns into a dbt model contract
    (``config(contract={enforced: true})`` + per-column ``data_type`` +
    ``constraints:``). It carries the column's logical UMF type plus the
    precision/scale/length needed to render a concrete adapter SQL type, and a
    ``not_null`` flag derived from UMF nullability.

    The CORE never mentions any dbt or SQL-dialect type name -- it hands back the
    *logical* UMF ``data_type`` (e.g. ``"INTEGER"``, ``"DECIMAL"``, ``"VARCHAR"``)
    and the modifiers, and the backend maps those to its adapter's SQL types.

    Attributes:
    ----------
        name: the column name.
        data_type: the UMF logical type (``VARCHAR``/``DECIMAL``/``INTEGER``/
            ``DATE``/``DATETIME``/``TIMESTAMP``/``BOOLEAN``/``TEXT``/``CHAR``/
            ``FLOAT``), upper-cased.
        not_null: ``True`` when the column is non-nullable in every context (so a
            ``not_null`` constraint applies); ``False`` for a nullable column.
        length: VARCHAR/CHAR length modifier (UMF ``length``), or ``None``.
        precision: DECIMAL precision (UMF ``precision``), or ``None``.
        scale: DECIMAL scale (UMF ``scale``), or ``None``.
    """

    name: str
    data_type: str
    not_null: bool
    length: int | None = None
    precision: int | None = None
    scale: int | None = None


def _column_not_null(col: dict[str, Any]) -> bool:
    """Resolve a column's not-null contract from its UMF ``nullable``.

    Mirrors :func:`tablespec.schemas.generators._resolve_nullable` (a column is
    nullable when missing, when ``True``, or when every context allows null), and
    inverts it: the contract is ``not_null`` only when the column is required in
    at least one context. The derivation is duplicated here (rather than imported
    from ``schemas.generators``) to keep ``tablespec.core`` self-contained.
    """
    nullable = col.get("nullable")
    if nullable is None:
        return False
    if isinstance(nullable, bool):
        return not nullable
    if isinstance(nullable, dict):
        # not_null iff at least one context forbids null (matches is_required()).
        return not (all(nullable.values()) if nullable else True)
    return False


def column_contracts(umf_data: dict[str, Any]) -> list[ColumnContract]:
    """Derive a :class:`ColumnContract` for every column, in UMF column order.

    Reuses the same type/precision/scale/length information ``generate_sql_ddl``
    derives (UMF ``data_type`` + ``length``/``precision``/``scale``) so the
    contract types are consistent with the SQL DDL. The backend maps the logical
    UMF type to its adapter SQL type.
    """
    out: list[ColumnContract] = []
    for col in umf_data.get("columns") or []:
        name = col.get("name")
        if not name:
            continue
        out.append(
            ColumnContract(
                name=name,
                data_type=str(col.get("data_type", "VARCHAR")).upper(),
                not_null=_column_not_null(col),
                length=col.get("length"),
                precision=col.get("precision"),
                scale=col.get("scale"),
            )
        )
    return out


def _iter_foreign_keys(umf_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the table's foreign_keys as plain dicts (model_dump form)."""
    rels = umf_data.get("relationships") or {}
    fks = rels.get("foreign_keys") or []
    return [fk for fk in fks if isinstance(fk, dict)]


def relationship_tests(
    umf_data: dict[str, Any],
    resolve_target: ResolveTarget,
) -> list[ColumnTest]:
    """Derive the FK ``relationship`` tests for a table.

    For each ``foreign_keys`` entry: cross-pipeline FKs are skipped (they are not
    model edges); the logical ``references_table`` is handed to ``resolve_target``
    and a ``None`` result SKIPS the test (unresolvable / external / not in the
    rendered set). Each surviving FK yields ONE single-column relationship test on
    its own column (composite FKs are not expressible in dbt-core core and are out
    of scope; each scalar FK is independent).

    Results are sorted by source column for deterministic emission.
    """
    out: list[ColumnTest] = []
    for fk in _iter_foreign_keys(umf_data):
        if fk.get("cross_pipeline"):
            continue
        column = fk.get("column")
        ref_table = fk.get("references_table")
        ref_column = fk.get("references_column")
        if not column or not ref_table or not ref_column:
            continue
        to_model = resolve_target(ref_table)
        if to_model is None:
            # Unresolvable / external target -> skip (never point at a missing model).
            continue
        out.append(
            ColumnTest.relationship(column, to_model=to_model, to_field=ref_column)
        )
    return sorted(out, key=lambda t: t.column)


def _iter_set_expectations(umf_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield every ``expect_column_values_to_be_in_set`` expectation dict.

    Reads the unified ``expectations.expectations`` suite first, then falls back
    to the legacy ``validation_rules.expectations`` GX-style list so older UMFs
    still surface their domain enums.
    """
    found: list[dict[str, Any]] = []

    suite = umf_data.get("expectations") or {}
    for exp in suite.get("expectations") or []:
        if isinstance(exp, dict) and exp.get("type") == _SET_MEMBERSHIP_TYPE:
            found.append(exp)

    legacy = (umf_data.get("validation_rules") or {}).get("expectations") or []
    for exp in legacy:
        if isinstance(exp, dict):
            etype = exp.get("type") or exp.get("expectation_type")
            if etype == _SET_MEMBERSHIP_TYPE:
                found.append(exp)

    return found


def accepted_values_tests(umf_data: dict[str, Any]) -> list[ColumnTest]:
    """Derive ``accepted_values`` tests from set-membership expectations.

    One test per column carrying an ``expect_column_values_to_be_in_set`` with a
    non-empty ``value_set``. If the same column appears more than once, the first
    non-empty set wins (deterministic). Columns with no such expectation get no
    test (no spurious accepted_values).
    """
    by_column: dict[str, ColumnTest] = {}
    for exp in _iter_set_expectations(umf_data):
        kwargs = exp.get("kwargs") or {}
        column = kwargs.get("column")
        value_set = kwargs.get("value_set")
        if not column or not value_set:
            continue
        if column in by_column:
            continue
        by_column[column] = ColumnTest.accepted_values(column, values=list(value_set))
    return [by_column[c] for c in sorted(by_column)]


def column_tests(
    umf_data: dict[str, Any],
    resolve_target: ResolveTarget,
) -> list[ColumnTest]:
    """All schema-test facts for a table: relationships + accepted_values.

    Sorted by ``(column, kind)`` so a column carrying both an FK and a domain enum
    emits both tests deterministically.
    """
    tests = relationship_tests(umf_data, resolve_target) + accepted_values_tests(
        umf_data
    )
    return sorted(tests, key=lambda t: (t.column, t.kind))


__all__ = [
    "ColumnContract",
    "ColumnTest",
    "ResolveTarget",
    "accepted_values_tests",
    "column_contracts",
    "column_tests",
    "relationship_tests",
]
