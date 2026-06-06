"""SQL-statement runtime helpers shared by the backbone and the conformance engines.

These live in the shipped package (not the test tree) so the runtime backbone can
split a compiled multi-statement ingest artifact into executable statements without
importing ``tests/`` (a wheel ships no test tree). The conformance engines re-export
``split_sql_statements`` for backwards compatibility.
"""

from __future__ import annotations


def split_sql_statements(sql: str) -> list[str]:
    """Split a multi-statement ingest artifact into executable statements.

    Comment lines (``-- ...``) are stripped first (some warning comments contain a
    ``;``), then the text is split on ``;``. The artifact never contains a ``;``
    inside a string literal, so a plain split of the de-commented text is safe.
    """
    decommented = "\n".join(
        ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")
    )
    statements: list[str] = []
    for chunk in decommented.split(";"):
        stmt = chunk.strip()
        if stmt:
            statements.append(stmt)
    return statements
