"""SQL pretty-printer for derivation expressions.

Thin wrapper around ``sqlparse.format`` so multi-line CASE statements and
similar constructs render with consistent indentation in the guidebook.
Lineage rendering must never crash on weird input — if sqlparse raises,
return the original text untouched.
"""

from __future__ import annotations

import logging

import sqlparse

logger = logging.getLogger(__name__)


def format_sql(text: str) -> str:
    """Return ``text`` reformatted with consistent indentation and casing.

    Falls back to the original ``text`` on any sqlparse error (we'd rather
    show unformatted SQL than fail page generation).
    """
    if not text or not text.strip():
        return text
    try:
        return sqlparse.format(
            text,
            reindent=True,
            keyword_case="upper",
            strip_comments=False,
            indent_width=2,
        )
    except Exception as exc:
        logger.warning("sqlparse.format failed (returning original text): %s", exc)
        return text
