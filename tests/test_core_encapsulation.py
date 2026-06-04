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

SRC = Path(__file__).parent.parent / "src" / "tablespec"

CORE_MODULES = [
    SRC / "core" / "__init__.py",
    SRC / "core" / "ir.py",
    SRC / "core" / "relations.py",
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
