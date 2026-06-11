"""Raw-file header resolution: canonical column lookup + header mapping.

These are the utilities ``tablespec.merge`` consumes to rename raw file
headers to canonical UMF column names before merging: a lookup keyed by every
known spelling of each column (``name``, ``canonical_name``, ``aliases``) and
a mapper that resolves a file's actual headers through that lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from tablespec.models.umf import UMF

#: Column ``source`` values that never appear as raw file headers.
_NON_DATA_SOURCES: frozenset[str] = frozenset({"filename", "metadata", "derived"})


@dataclass(frozen=True)
class HeaderMatch:
    """A resolved header: the canonical UMF column and how it matched."""

    umf_column: str
    matched_via: str  # "name" | "canonical_name" | "alias"


def _normalize(header: str) -> str:
    """Normalize a header for lookup: strip surrounding whitespace, casefold."""
    return header.strip().casefold()


def build_column_lookup(
    umf: UMF, *, include_non_data: bool = False
) -> dict[str, HeaderMatch]:
    """Build a normalized header -> canonical column lookup for *umf*.

    Keys are the normalized (stripped + casefolded) spellings of each column's
    ``name``, ``canonical_name``, and ``aliases``; values name the canonical
    UMF column. Exact names take precedence over canonical names, which take
    precedence over aliases; within a tier the first column wins (an entry is
    never overwritten by a later collision).

    Args:
        umf: Table spec providing the columns.
        include_non_data: When False, columns whose ``source`` is
            ``filename`` / ``metadata`` / ``derived`` are excluded (they are
            synthesized during ingestion and never appear as raw file
            headers). When True every column is included -- e.g. for re-reading
            previously merged output that carries those columns.

    Returns:
        Mapping of normalized header spelling to :class:`HeaderMatch`.
    """
    columns = [
        col
        for col in umf.columns
        if include_non_data or col.source not in _NON_DATA_SOURCES
    ]
    lookup: dict[str, HeaderMatch] = {}

    def _add(spelling: str | None, umf_column: str, via: str) -> None:
        if not spelling:
            return
        key = _normalize(spelling)
        if key and key not in lookup:
            lookup[key] = HeaderMatch(umf_column=umf_column, matched_via=via)

    for col in columns:
        _add(col.name, col.name, "name")
    for col in columns:
        _add(col.canonical_name, col.name, "canonical_name")
    for col in columns:
        for alias in col.aliases or []:
            _add(alias, col.name, "alias")
    return lookup


def map_headers(
    columns: Sequence[str], lookup: Mapping[str, HeaderMatch]
) -> dict[str, HeaderMatch]:
    """Resolve raw file headers to canonical UMF columns via *lookup*.

    Returns ``{raw_header: HeaderMatch}`` for every header that resolves.
    Unrecognized headers are omitted (callers decide whether unmapped headers
    are an error -- ``tablespec.merge`` only requires its primary-key and
    timestamp columns to resolve). If two raw headers resolve to the same
    canonical column, the first occurrence wins and later duplicates are
    omitted so downstream renames cannot produce duplicate column names.
    """
    mapping: dict[str, HeaderMatch] = {}
    claimed: set[str] = set()
    for raw in columns:
        match = lookup.get(_normalize(raw))
        if match is None or match.umf_column in claimed:
            continue
        claimed.add(match.umf_column)
        mapping[raw] = match
    return mapping
