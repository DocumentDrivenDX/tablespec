"""Extract column references from derivation SQL expressions.

Mirrors how ``DeltaSQLGenerator`` reads expressions: bare identifiers are
column names of the candidate's table, ``base.<alias>__<col>`` references a
joined table's column (also when written without ``base.``), ``base.<col>``
references the base view, and
``{{col:anchor(.field)}}`` references another column of the same table.
References are candidates only; the builder keeps those matching real columns.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

# Same pattern as DeltaSQLGenerator._COL_PLACEHOLDER_RE.
_COL_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*col:\s*(?P<anchor>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\.(?P<field>[A-Za-z_][A-Za-z0-9_]*))?\s*\}\}"
)
_TEMPLATE_VAR_RE = re.compile(r"\{\{[^}]*\}\}")
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_BASE_REF_RE = re.compile(r"\bbase\.([A-Za-z_][A-Za-z0-9_]*)")
# Identifier not part of a qualified name (no '.' on either side) and not a function call.
_BARE_RE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)(?![\w.])(?!\s*\()")


@dataclass(frozen=True)
class ExprRef:
    """A column reference found in an expression."""

    kind: Literal["placeholder", "prefixed", "base", "bare"]
    column: str
    alias: str | None = None
    field: str | None = None


def extract_refs(expression: str) -> list[ExprRef]:
    """Return the distinct column references in ``expression``, in order of appearance."""
    refs: list[ExprRef] = []

    def _blank(match: re.Match[str]) -> str:
        return " " * len(match.group(0))

    for m in _COL_PLACEHOLDER_RE.finditer(expression):
        refs.append(ExprRef("placeholder", m.group("anchor"), field=m.group("field")))
    text = _COL_PLACEHOLDER_RE.sub(_blank, expression)
    text = _TEMPLATE_VAR_RE.sub(_blank, text)
    text = _STRING_LITERAL_RE.sub(_blank, text)

    for m in _BASE_REF_RE.finditer(text):
        name = m.group(1)
        if "__" in name:
            alias, column = name.rsplit("__", 1)
            refs.append(ExprRef("prefixed", column, alias=alias))
        else:
            refs.append(ExprRef("base", name))
    text = _BASE_REF_RE.sub(_blank, text)

    for m in _BARE_RE.finditer(text):
        name = m.group(1)
        # Unqualified ``alias__col`` still names a flattened joined-table column of the view.
        if "__" in name.strip("_"):
            alias, column = name.rsplit("__", 1)
            refs.append(ExprRef("prefixed", column, alias=alias))
        else:
            refs.append(ExprRef("bare", name))
    return list(dict.fromkeys(refs))
