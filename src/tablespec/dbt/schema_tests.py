"""Render dbt ``schema.yml`` generic tests from engine-agnostic schema facts.

The derivation (which FK becomes a ``relationships`` test, which domain enum
becomes an ``accepted_values`` test) lives in
:mod:`tablespec.core.schema_facts`; this module owns ONLY the dbt YAML *text* for
those facts, so both emitters (``single_table.py`` and ``project.py``) share one
rendering and can never drift.

The emitted text is intentionally byte-stable with the historical hand-rolled
relationships block (golden ``dbt_dag_project/member_claims/models/schema.yml``):

    - name: <column>
      data_tests:
        - relationships:
            arguments:
              to: ref('<model>')
              field: <field>
        - accepted_values:
            arguments:
              values: ["A", "B"]

The functions return *lists of indented lines* (no trailing newline) so a caller
assembles them into a larger ``columns:`` block. Pure text emission -- importing
this module never imports any ``dbt`` package.
"""

from __future__ import annotations

from tablespec.core.schema_facts import ColumnTest

# Indentation for a test entry sitting under a column's ``data_tests:`` list,
# where the column itself is at 6 spaces (``      - name: x``) -- matching the
# existing schema.yml layout used by both emitters.
_TEST_INDENT = "          "  # 10 spaces: ``          - relationships:``
_ARG_INDENT = "              "  # 14 spaces: under ``arguments:``


def _yaml_scalar(value: object) -> str:
    """Render one value_set element as a type-faithful inline YAML scalar.

    Numbers and booleans emit unquoted (``1``, ``2.5``, ``true``) so an INTEGER /
    DECIMAL / BOOLEAN domain compares like-typed against the warehouse column;
    strings emit double-quoted. ``bool`` is checked before ``int`` because
    ``bool`` is a subclass of ``int`` in Python.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_inline_list(values: tuple[object, ...]) -> str:
    """Render a value_set as an inline YAML flow list, preserving element types."""
    return "[" + ", ".join(_yaml_scalar(v) for v in values) + "]"


def render_relationship(test: ColumnTest) -> list[str]:
    """Render a ``relationships`` generic test (lines under ``data_tests:``)."""
    assert test.kind == "relationship"
    assert test.to_model is not None
    assert test.to_field is not None
    return [
        f"{_TEST_INDENT}- relationships:",
        f"{_ARG_INDENT}arguments:",
        f"{_ARG_INDENT}  to: ref('{test.to_model}')",
        f"{_ARG_INDENT}  field: {test.to_field}",
    ]


def render_accepted_values(test: ColumnTest) -> list[str]:
    """Render an ``accepted_values`` generic test (lines under ``data_tests:``)."""
    assert test.kind == "accepted_values"
    assert test.values is not None
    return [
        f"{_TEST_INDENT}- accepted_values:",
        f"{_ARG_INDENT}arguments:",
        f"{_ARG_INDENT}  values: {_yaml_inline_list(test.values)}",
    ]


def render_column_test(test: ColumnTest) -> list[str]:
    """Render a single :class:`ColumnTest` to its ``data_tests:`` entry lines."""
    if test.kind == "relationship":
        return render_relationship(test)
    if test.kind == "accepted_values":
        return render_accepted_values(test)
    msg = f"unknown schema-test kind: {test.kind!r}"
    raise ValueError(msg)


def render_tests_for_column(tests: list[ColumnTest]) -> list[str]:
    """Render the ``data_tests:`` block lines for one column's tests.

    Returns the ``        data_tests:`` header followed by each test's entry, or
    an empty list when there are no tests (caller emits the bare ``- name:``).
    """
    if not tests:
        return []
    lines = ["        data_tests:"]
    for test in tests:
        lines.extend(render_column_test(test))
    return lines


__all__ = [
    "render_accepted_values",
    "render_column_test",
    "render_relationship",
    "render_tests_for_column",
]
