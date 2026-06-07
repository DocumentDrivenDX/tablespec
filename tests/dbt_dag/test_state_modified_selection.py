"""Item (3) state_modified_ci -- functional tests for the changed-table selection.

Proves the engine-agnostic :class:`~tablespec.core.selection.ChangeSet` derivation
(``core.selection.change_set`` over two real UMF directory snapshots) and the
dbt-aware mapping (``dbt.selection.select_expression``) WITHOUT invoking dbt:

  * AC3.1/AC3.4 (set): editing exactly one table's UMF yields ``{that_table}``;
    an added table appears; a removed table is flagged and EXCLUDED from the
    buildable set.
  * AC3.2 (set + expression): OLD == NEW -> empty ChangeSet -> the canonical
    unsatisfiable selector (NOT the empty string, NOT the whole project).
  * AC3.4 (removed): a removed table never appears in a selection expression.

The live ``dbt ls``/``dbt build`` proofs (the selection actually resolves to the
right node set in dbt's graph, and the empty selector builds 0 models) live in
``test_state_modified_e2e.py``. These tests are JVM-free and dbt-package-free.
"""

# dbt state:modified selection coverage.
# @covers US-025-AC4

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from tablespec.core.selection import ChangeSet, change_set
from tablespec.dbt.registry import NodeRegistry
from tablespec.dbt.selection import (
    EMPTY_SELECTION,
    select_expression,
    state_modified_expression,
)
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_dag"
TABLES = ["member", "claims", "member_claims"]


def _copy_snapshot(dest: Path) -> Path:
    """Copy the committed member_claims UMF set into *dest* as one snapshot dir."""
    dest.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        shutil.copy(FIXTURE_DIR / f"{t}.umf.yaml", dest / f"{t}.umf.yaml")
    return dest


def _edit_member_column(umf_dir: Path) -> None:
    """Mutate the ``member`` UMF so the per-table diff is non-empty.

    Changes a column description -- a real, diff-visible edit (UMFDiff reports it
    as a column modification) that does NOT touch ``claims`` or ``member_claims``.
    """
    path = umf_dir / "member.umf.yaml"
    data = yaml.safe_load(path.read_text())
    data["columns"][0]["description"] = "EDITED for state:modified selection test"
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _registry() -> NodeRegistry:
    umfs = [
        UMF(**yaml.safe_load((FIXTURE_DIR / f"{t}.umf.yaml").read_text()))
        for t in TABLES
    ]
    return NodeRegistry(umfs)


# --------------------------------------------------------------------------- #
# AC3.1 / AC3.2 / AC3.4 -- the core ChangeSet derivation
# --------------------------------------------------------------------------- #


def test_changeset_one_edited_table(tmp_path: Path) -> None:
    """AC3.1 (set): editing exactly ``member`` -> ChangeSet.modified == {member}."""
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")
    _edit_member_column(new_dir)

    cs = change_set(old_dir, new_dir)
    assert cs.modified == frozenset({"member"})
    assert cs.added == frozenset()
    assert cs.removed == frozenset()
    assert cs.affected == frozenset({"member"})
    # Unrelated tables are NOT in the set (proves it is not "everything changed").
    assert "claims" not in cs.affected
    assert "member_claims" not in cs.affected


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("primary_key", lambda d: d.update(primary_key=["claim_id", "member_id"])),
        ("ingestion.mode", lambda d: d["ingestion"].update(mode="snapshot")),
        (
            "ingestion.order_by",
            lambda d: d["ingestion"].update(order_by=["_source_file"]),
        ),
    ],
)
def test_changeset_detects_structural_field_change(
    tmp_path: Path, field, mutate
) -> None:
    """Regression: structural fields UMFDiff does NOT diff (primary_key, ingestion,
    ...) still mark a table modified, so CI never under-selects a model whose merge
    key or materialization changed (would otherwise silently skip the rebuild).
    """
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")
    path = new_dir / "claims.umf.yaml"
    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    cs = change_set(old_dir, new_dir)
    assert "claims" in cs.modified, f"{field} change must mark claims modified"


def test_changeset_unchanged_is_empty(tmp_path: Path) -> None:
    """AC3.2 (set): OLD == NEW -> an empty ChangeSet (nothing selected)."""
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")

    cs = change_set(old_dir, new_dir)
    assert cs.is_empty
    assert cs.modified == frozenset()
    assert cs.added == frozenset()
    assert cs.removed == frozenset()
    assert cs.affected == frozenset()


def test_changeset_added_table(tmp_path: Path) -> None:
    """AC3.4: a table present only in NEW is classified ADDED and is affected."""
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")
    # Remove member_claims from OLD so it is "added" in NEW.
    (old_dir / "member_claims.umf.yaml").unlink()

    cs = change_set(old_dir, new_dir)
    assert cs.added == frozenset({"member_claims"})
    assert "member_claims" in cs.affected
    assert cs.removed == frozenset()


def test_changeset_removed_table_flagged_not_affected(tmp_path: Path) -> None:
    """AC3.4: a table present only in OLD is REMOVED and EXCLUDED from affected.

    Removed tables must be encodable distinctly (must-fix: a bare frozenset[str]
    cannot do this) AND must never reach the buildable selection.
    """
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")
    # Drop member_claims from NEW -> it is "removed".
    (new_dir / "member_claims.umf.yaml").unlink()

    cs = change_set(old_dir, new_dir)
    assert cs.removed == frozenset({"member_claims"})
    assert "member_claims" not in cs.affected
    assert cs.modified == frozenset()
    assert cs.added == frozenset()


# --------------------------------------------------------------------------- #
# AC3.1 / AC3.2 / AC3.3 / AC3.4 -- the dbt selection expression mapping
# --------------------------------------------------------------------------- #


def test_selection_expression_one_table_with_fanout() -> None:
    """AC3.1/AC3.3: {member} -> ``ingested_member+`` (its model + descendants).

    ``member`` is a landing table, so its model is ``ingested_member``; the
    trailing ``+`` is the descendant operator (so dbt also picks up
    ``gold_member_claims``). The expression names ONLY member's model -- not
    ``ingested_claims`` and not the whole project.
    """
    reg = _registry()
    cs = ChangeSet(modified=frozenset({"member"}))
    expr = select_expression(cs, reg)
    assert expr == "ingested_member+"
    assert "ingested_claims" not in expr
    assert "gold_member_claims" not in expr  # picked up by dbt graph via '+', not text


def test_selection_expression_gold_table_uses_gold_model() -> None:
    """AC3.1: a pure-gold changed table maps to its ``gold_<t>`` model id."""
    reg = _registry()
    cs = ChangeSet(modified=frozenset({"member_claims"}))
    expr = select_expression(cs, reg)
    assert expr == "gold_member_claims+"


def test_selection_expression_multiple_tables_union() -> None:
    """Two changed tables -> a space-joined union, each with its own fanout."""
    reg = _registry()
    cs = ChangeSet(modified=frozenset({"member", "claims"}))
    expr = select_expression(cs, reg)
    # sorted by table name: claims, member
    assert expr == "ingested_claims+ ingested_member+"


def test_empty_changeset_maps_to_unsatisfiable_selector() -> None:
    """AC3.2: empty ChangeSet -> the concrete unsatisfiable selector, NOT ''.

    Must-fix: pin the empty-selection contract to a concrete, safe selector
    instead of the empty string (which dbt treats as "the whole project").
    """
    reg = _registry()
    expr = select_expression(ChangeSet(), reg)
    assert expr == EMPTY_SELECTION
    assert expr != ""
    assert expr.startswith("fqn:")


def test_selection_removed_table_not_referenced() -> None:
    """AC3.4 (must-fix): a removed table NEVER appears in a selection expression.

    A ChangeSet whose ONLY change is a removed table maps to the unsatisfiable
    selector (no deleted model is referenced); a removed table alongside a real
    modification contributes nothing to the union.
    """
    reg = _registry()
    # Removed-only -> nothing buildable -> empty selector.
    only_removed = ChangeSet(removed=frozenset({"member_claims"}))
    assert select_expression(only_removed, reg) == EMPTY_SELECTION

    # Removed + a real modification -> only the modified table's model.
    mixed = ChangeSet(
        modified=frozenset({"member"}),
        removed=frozenset({"member_claims"}),
    )
    expr = select_expression(mixed, reg)
    assert expr == "ingested_member+"
    assert "member_claims" not in expr


def test_changeset_duplicate_table_name_in_snapshot_fails(tmp_path: Path) -> None:
    """A snapshot with two files declaring the same table_name fails loudly.

    Old/new files pair by table_name, so a duplicate within one snapshot makes the
    pairing ambiguous -- ``change_set`` must raise rather than silently drop a spec.
    """
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")
    # A second file in NEW that also declares table_name == 'member'.
    dup = yaml.safe_load((FIXTURE_DIR / "member.umf.yaml").read_text())
    (new_dir / "member_copy.umf.yaml").write_text(yaml.safe_dump(dup, sort_keys=False))

    with pytest.raises(ValueError, match="Duplicate table_name 'member'"):
        change_set(old_dir, new_dir)


def test_end_to_end_removed_table_never_in_expression(tmp_path: Path) -> None:
    """AC3.4 (full path): change_set -> select_expression never names a removed model.

    Exercises the REAL pipeline (not a hand-built ChangeSet): drop one table from
    the NEW snapshot so ``change_set`` classifies it removed, build the registry
    from the NEW snapshot (where that table's model no longer exists), and assert
    the derived selection references no deleted model. Here ``member_claims`` (the
    only gold table) is removed AND ``member`` is edited, so the expression must be
    exactly ``member``'s staging model with fanout -- and must not mention the
    removed gold model.
    """
    old_dir = _copy_snapshot(tmp_path / "old")
    new_dir = _copy_snapshot(tmp_path / "new")
    (new_dir / "member_claims.umf.yaml").unlink()  # removed in NEW
    _edit_member_column(new_dir)  # member modified in NEW

    cs = change_set(old_dir, new_dir)
    assert cs.removed == frozenset({"member_claims"})
    assert cs.modified == frozenset({"member"})

    # Registry reflects the NEW (post-removal) project: no gold_member_claims node.
    new_umfs = [
        UMF(**yaml.safe_load((new_dir / f"{t}.umf.yaml").read_text()))
        for t in ("member", "claims")
    ]
    reg = NodeRegistry(new_umfs)
    expr = select_expression(cs, reg)
    assert expr == "ingested_member+"
    assert "member_claims" not in expr
    assert "gold_" not in expr


def test_affected_subtracts_removed_defensively() -> None:
    """A malformed ChangeSet listing a table modified AND removed never selects it.

    Defensive contract (a directly-constructed ChangeSet bypasses change_set's
    disjoint guarantee): ``removed`` wins, so a deleted model is never referenced.
    """
    reg = _registry()
    cs = ChangeSet(
        modified=frozenset({"member_claims"}),
        removed=frozenset({"member_claims"}),
    )
    assert cs.affected == frozenset()
    assert select_expression(cs, reg) == EMPTY_SELECTION


def test_state_modified_native_expression_documented() -> None:
    """The dbt-native equivalent selector is exposed for manifest-based CI."""
    assert state_modified_expression() == "state:modified+"
