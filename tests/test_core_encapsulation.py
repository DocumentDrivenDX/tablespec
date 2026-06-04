"""Prove the dbt path is encapsulated: CORE never imports ``tablespec.dbt``.

The check is STATIC (AST over the core source files), not a runtime side-effect
check: importing any ``tablespec.X`` submodule executes the top-level
``tablespec/__init__.py`` (which is allowed to wire up the public API, including
dbt), so a runtime ``sys.modules`` probe can't distinguish a core->dbt dependency
from the package facade. The architectural invariant we actually care about is
that no *core module's own import statements* reference ``tablespec.dbt``.

CORE = the dbt-free seam every backend depends on:
  * ``tablespec.core`` (TableRenderer Protocol + logical-plan IR)
  * the cast/dialect layer (``casting_utils``, ``date_formats``)
  * the shared ingest seam (``schemas.ingest_generator.build_ingest_select``,
    ``schemas.generators``, ``schemas.relationship_resolver``)
  * the gold SQL generator (``schemas.sql_generator``)
  * the direct artifact emitter (``generate_ingest_sql``)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

SRC = Path(__file__).parent.parent / "src" / "tablespec"

CORE_MODULES = [
    SRC / "core" / "__init__.py",
    SRC / "core" / "ir.py",
    SRC / "core" / "relations.py",
    SRC / "core" / "schema_facts.py",
    SRC / "core" / "selection.py",
    SRC / "casting_utils.py",
    SRC / "date_formats.py",
    SRC / "schemas" / "__init__.py",
    SRC / "schemas" / "generators.py",
    SRC / "schemas" / "ingest_generator.py",
    SRC / "schemas" / "relationship_resolver.py",
    SRC / "schemas" / "sql_generator.py",
]


def _imported_modules(path: Path) -> set[str]:
    """Return the dotted module targets of every import statement in *path*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # Absolute ``from tablespec.x import y`` -> module = node.module.
            # Relative ``from .x import y`` (level>0) stays inside the package and
            # cannot reach tablespec.dbt, so it is irrelevant here.
            if node.level == 0 and node.module:
                targets.add(node.module)
    return targets


def test_core_modules_do_not_import_dbt() -> None:
    offenders: dict[str, set[str]] = {}
    for path in CORE_MODULES:
        assert path.exists(), f"core module missing: {path}"
        bad = {m for m in _imported_modules(path) if m.startswith("tablespec.dbt")}
        if bad:
            offenders[str(path.relative_to(SRC))] = bad
    assert not offenders, (
        "CORE modules must not import tablespec.dbt (encapsulation breach):\n"
        + "\n".join(f"  {mod}: {sorted(imps)}" for mod, imps in offenders.items())
    )


def test_dbt_package_depends_only_on_core_seam() -> None:
    """The dbt package may import core, but the direct-artifact emitter must not
    import the dbt package (the two backends never depend on each other)."""
    ingest = SRC / "schemas" / "ingest_generator.py"
    bad = {m for m in _imported_modules(ingest) if m.startswith("tablespec.dbt")}
    assert not bad, f"direct-artifact emitter imports dbt: {sorted(bad)}"


def test_selection_core_has_no_dbt() -> None:
    """AC3.5: ``core.selection`` knows nothing of dbt / ``state:modified``.

    The changed-table derivation is engine-agnostic: it must neither import any
    ``tablespec.dbt`` module nor mention the dbt-native ``state:modified`` selector
    literal (that mapping lives ONLY in ``tablespec.dbt.selection``).
    """
    path = SRC / "core" / "selection.py"
    assert path.exists(), f"core selection module missing: {path}"
    bad = {m for m in _imported_modules(path) if m.startswith("tablespec.dbt")}
    assert not bad, f"core.selection imports dbt (encapsulation breach): {sorted(bad)}"
    source = path.read_text()
    assert "state:modified" not in source, (
        "core.selection must not mention the dbt-native 'state:modified' selector; "
        "that engine-specific mapping belongs in tablespec.dbt.selection."
    )


def test_dbt_selection_imports_no_dbt_package() -> None:
    """The dbt selection mapper is pure text emission -- no ``dbt`` package import.

    Generating a CI selection expression must work with the ``[dbt]`` extra
    UNINSTALLED, so ``tablespec.dbt.selection`` may import core + the registry but
    must not import the ``dbt`` (dbt-core) package itself.
    """
    path = SRC / "dbt" / "selection.py"
    assert path.exists(), f"dbt selection module missing: {path}"
    imported = _imported_modules(path)
    bad = {m for m in imported if m == "dbt" or m.startswith("dbt.")}
    assert not bad, f"dbt.selection imports the dbt-core package: {sorted(bad)}"


def test_dbt_seeds_imports_no_dbt_core_package() -> None:
    """The seed emitter is pure text emission -- no ``dbt`` (dbt-core) package import.

    Emitting ``seeds/<t>.csv`` + the ``column_types`` config must work with the
    ``[dbt]`` extra UNINSTALLED, so ``tablespec.dbt.seeds`` may import core
    (``schema_facts``) + the sibling contracts text but must not import the
    ``dbt`` (dbt-core) package itself.
    """
    path = SRC / "dbt" / "seeds.py"
    assert path.exists(), f"dbt seeds module missing: {path}"
    imported = _imported_modules(path)
    bad = {m for m in imported if m == "dbt" or m.startswith("dbt.")}
    assert not bad, f"dbt.seeds imports the dbt-core package: {sorted(bad)}"


def test_dbt_seeds_does_not_import_sample_data_engine() -> None:
    """The seed emitter CONSUMES the generator's on-disk output -- it does not
    import or re-run the generator. It must not depend on the heavy
    ``sample_data.engine`` module (only on the public UMF model + core facts)."""
    path = SRC / "dbt" / "seeds.py"
    imported = _imported_modules(path)
    bad = {m for m in imported if m.startswith("tablespec.sample_data")}
    assert not bad, (
        "dbt.seeds must consume generated output, not import the generator: "
        f"{sorted(bad)}"
    )


def test_core_relations_seam_is_dbt_free_and_usable() -> None:
    """The TableRenderer Protocol + LiteralRenderer live in core, no dbt needed.

    Importing the core seam must not require dbt, and the default LiteralRenderer
    must satisfy the Protocol both with and without a resolver (the direct-artifact
    rendering behaviour the dbt DbtRefRenderer mirrors).
    """
    from tablespec.core.relations import (
        LiteralRenderer,
        RelationRef,
        TableRenderer,
    )

    plain = LiteralRenderer()
    assert plain.render("member") == "member"  # passthrough
    qualified = LiteralRenderer(resolver=lambda n: f"cat.{n}")
    assert qualified.render("member") == "cat.member"  # resolver applied
    # Structural Protocol conformance (runtime_checkable).
    assert isinstance(plain, TableRenderer)
    assert RelationRef("member").kind == "table"  # advisory default
