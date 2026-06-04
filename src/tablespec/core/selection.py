"""Engine-agnostic *changed-table set* over two UMF directory snapshots.

This is the CORE seam feeding the dbt impacted-model CI selection
(``tablespec.dbt.selection``) WITHOUT any dbt knowledge living here. It answers a
single question over two snapshots of a UMF repo (an ``old`` and a ``new``
directory of ``*.umf.yaml`` files): *which tables changed?*

It does NOT mention dbt, any dbt selector syntax, ``ref()`` or
``ingested_``/``gold_`` model names -- it hands back a neutral :class:`ChangeSet`
of logical ``table_name``s split by status (modified / added / removed). A
backend (``tablespec.dbt.selection``) maps that into its own selection syntax.

Implementation note: there is no repo-wide diff in ``tablespec.umf_diff`` -- only
the per-table :class:`~tablespec.umf_diff.UMFDiff` (``UMFDiff(old_umf, new_umf)``
over ONE table). :func:`change_set` PAIRS files across the two directories by
``table_name`` and runs that per-table diff, marking a table *modified* iff its
``UMFDiff`` yields any non-empty column / validation / metadata change. Tables
present only in ``new`` are *added*; tables present only in ``old`` are *removed*
(flagged so a backend never points a selection at a deleted model).

Import rule (``tests/test_core_encapsulation.py``): nothing here imports
``tablespec.dbt``; this module is pure-Python value derivation over UMF models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from tablespec.models.umf import UMF, load_umf_from_yaml
from tablespec.umf_diff import UMFDiff


class ChangeStatus(str, Enum):
    """How a table changed between the ``old`` and ``new`` snapshots."""

    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"


@dataclass(frozen=True)
class ChangeSet:
    """The changed-table set across two UMF snapshots, split by status.

    A plain ``frozenset[str]`` cannot encode *removed* tables distinctly from
    changed ones (a removed table must never be mapped to a selection pointing at
    a deleted model), so the set is carried as three disjoint frozensets.

    Attributes:
        modified: tables present in both snapshots whose UMF spec changed.
        added: tables present only in the ``new`` snapshot.
        removed: tables present only in the ``old`` snapshot (deleted).
    """

    modified: frozenset[str] = field(default_factory=frozenset)
    added: frozenset[str] = field(default_factory=frozenset)
    removed: frozenset[str] = field(default_factory=frozenset)

    @property
    def affected(self) -> frozenset[str]:
        """Tables whose models should be (re)built: modified + added.

        Removed tables are intentionally EXCLUDED -- their model no longer exists,
        so a backend must never produce a selection that references them. The
        subtraction is DEFENSIVE: a directly-constructed (non-:func:`change_set`)
        ChangeSet could list a name as both modified and removed; ``removed`` wins
        so a deleted model is never referenced even from a malformed set.
        """
        return (self.modified | self.added) - self.removed

    @property
    def is_empty(self) -> bool:
        """``True`` when nothing changed (no modified, added or removed table)."""
        return not (self.modified or self.added or self.removed)


def _table_diff_is_nonempty(old_umf: UMF, new_umf: UMF) -> bool:
    """``True`` iff the per-table :class:`UMFDiff` finds any real change.

    Wraps the existing per-table diff (the only diff the codebase has): a table is
    *modified* iff it carries at least one column, validation-rule, or table-level
    metadata change.
    """
    diff = UMFDiff(old_umf, new_umf)
    return bool(
        diff.get_column_changes()
        or diff.get_validation_changes()
        or diff.get_metadata_changes()
    )


def _load_umfs_by_table(directory: Path) -> dict[str, UMF]:
    """Load every ``*.umf.yaml`` under *directory*, keyed by ``table_name``.

    Raises:
        ValueError: two files in the directory declare the same ``table_name``
            (the pairing across snapshots would be ambiguous).
    """
    by_table: dict[str, UMF] = {}
    for path in sorted(directory.glob("*.umf.yaml")):
        umf = load_umf_from_yaml(path)
        if umf.table_name in by_table:
            msg = (
                f"Duplicate table_name {umf.table_name!r} in {directory} "
                f"(seen again in {path.name}); table names must be unique per "
                f"snapshot so old/new files pair unambiguously."
            )
            raise ValueError(msg)
        by_table[umf.table_name] = umf
    return by_table


def change_set(old_dir: str | Path, new_dir: str | Path) -> ChangeSet:
    """Compute the :class:`ChangeSet` between two UMF directory snapshots.

    Pairs ``*.umf.yaml`` files across the two directories by ``table_name`` and
    classifies each table:

      * in both, spec changed -> ``modified``,
      * in both, spec identical -> not in the set,
      * only in ``new`` -> ``added``,
      * only in ``old`` -> ``removed``.

    Args:
        old_dir: directory of the PRIOR UMF snapshot.
        new_dir: directory of the CURRENT UMF snapshot.

    Returns:
        A :class:`ChangeSet`. Empty (all three sets empty) when ``old == new``.
    """
    old_by_table = _load_umfs_by_table(Path(old_dir))
    new_by_table = _load_umfs_by_table(Path(new_dir))

    old_names = set(old_by_table)
    new_names = set(new_by_table)

    added = frozenset(new_names - old_names)
    removed = frozenset(old_names - new_names)
    modified = frozenset(
        name
        for name in old_names & new_names
        if _table_diff_is_nonempty(old_by_table[name], new_by_table[name])
    )
    return ChangeSet(modified=modified, added=added, removed=removed)


__all__ = ["ChangeSet", "ChangeStatus", "change_set"]
