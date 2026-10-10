"""Discover domains (bounded contexts) and resolve which ones a path covers.

A domain is any directory that contains a ``domain.yaml`` (see
:mod:`tablespec.models.domain`). Its tables are the split-format UMF
directories (``table.yaml``) and ``*.umf.json`` files found beneath it. The
directory that *holds* domain directories is a **domain root**; the domains in
one root are each other's siblings, and a ``domain.table`` qualifier resolves
among them. A ``domain.yaml`` nested inside another domain directory is
ignored, so the qualifier stays one segment.

Two questions are answered here, and nothing else (no rendering, no rules):

* :func:`discover_domains` -- load every domain in one root.
* :func:`resolve_domain_scopes` -- given *any* path a user might validate (a
  corpus root, one domain directory, one table inside a domain, or a directory
  far above several corpora), find the domain roots involved, load each root's
  full sibling set, and say which of those domains the path actually covers.
  Rules always run against the full sibling set, because a consumer's
  supplier lives next to it, not beneath it; findings are then narrowed to
  what the path covers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path

from tablespec.models.domain import (
    DOMAIN_FILENAME,
    DomainLoadError,
    DomainMetadata,
    Glossary,
    load_domain,
    load_glossary,
)
from tablespec.models.umf import UMF, load_umf_from_yaml
from tablespec.umf_loader import UMFLoader

logger = logging.getLogger(__name__)

UMF_YAML_SUFFIX = ".umf.yaml"
TABLE_FILENAME = "table.yaml"

_PRUNED_DIR_NAMES = frozenset({"node_modules", "__pycache__", "venv", "site-packages"})


def is_pruned_dir(name: str) -> bool:
    """Directories never searched for tables or domains: hidden dirs and vendored trees."""
    return name.startswith(".") or name in _PRUNED_DIR_NAMES


def iter_table_dirs(root: Path) -> list[Path]:
    """Every split-format table directory under ``root``, recursively, sorted.

    A table directory is one that contains ``table.yaml``. The walk does not
    descend into a table directory (its ``columns/`` holds no tables) and
    skips hidden and vendored directories.
    """
    root = Path(root)
    found: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not is_pruned_dir(d))
        if TABLE_FILENAME in filenames and Path(current) != root:
            found.append(Path(current))
            dirnames[:] = []
    return sorted(found)


@dataclass
class LoadedDomain:
    """A domain directory with its metadata, glossary, and tables loaded."""

    path: Path
    metadata: DomainMetadata
    glossary: Glossary | None = None
    tables: dict[str, UMF] = field(default_factory=dict)
    table_paths: dict[str, Path] = field(default_factory=dict)
    load_errors: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.metadata.name

    def table(self, name: str) -> UMF | None:
        """Look up a table by ``table_name`` or alias, case-insensitively."""
        needle = name.lower()
        hit = self.tables.get(needle)
        if hit is not None:
            return hit
        for umf in self.tables.values():
            if umf.aliases and needle in (a.lower() for a in umf.aliases):
                return umf
        return None

    def table_at(self, path: Path) -> str | None:
        """Return the ``table_name`` of the table loaded from ``path``, if any."""
        target = Path(path).resolve()
        for key, source in self.table_paths.items():
            if source == target:
                return self.tables[key].table_name
        return None


def _load_any_umf(path: Path) -> UMF:
    if path.is_file() and path.name.endswith(UMF_YAML_SUFFIX):
        return load_umf_from_yaml(path)
    return UMFLoader().load(path)


def _table_candidates(domain_dir: Path) -> list[Path]:
    candidates: list[Path] = sorted(
        {p.parent for p in domain_dir.rglob(TABLE_FILENAME)}
    )
    candidates += sorted(domain_dir.rglob("*.umf.json"))
    candidates += sorted(domain_dir.rglob(f"*{UMF_YAML_SUFFIX}"))
    return candidates


def load_domain_dir(domain_dir: Path) -> LoadedDomain:
    """Load one domain directory: ``domain.yaml``, its glossary, and its tables.

    Raises :class:`DomainLoadError` when ``domain.yaml`` or the glossary is
    invalid. A table that fails to load is recorded in ``load_errors`` and
    skipped, so one bad UMF does not hide the rest of the domain.
    """
    domain_dir = Path(domain_dir).resolve()
    meta = load_domain(domain_dir)
    glossary = load_glossary(domain_dir, meta)
    loaded = LoadedDomain(path=domain_dir, metadata=meta, glossary=glossary)
    for candidate in _table_candidates(domain_dir):
        try:
            umf = _load_any_umf(candidate)
        except Exception as exc:  # noqa: BLE001 - report and continue
            loaded.load_errors.append(f"{candidate}: {exc}")
            logger.warning("Skipping %s in domain %s: %s", candidate, meta.name, exc)
            continue
        key = umf.table_name.lower()
        if key in loaded.tables:
            loaded.load_errors.append(
                f"{candidate}: duplicate table '{umf.table_name}' in domain '{meta.name}'"
            )
            continue
        loaded.tables[key] = umf
        loaded.table_paths[key] = candidate.resolve()
    return loaded


def find_domain_dirs(root: Path) -> list[Path]:
    """Return the immediate child directories of ``root`` that hold a ``domain.yaml``.

    ``root`` itself is included when it holds one (a single-domain checkout).
    """
    root = Path(root).resolve()
    dirs: list[Path] = []
    if (root / DOMAIN_FILENAME).is_file():
        dirs.append(root)
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / DOMAIN_FILENAME).is_file():
            dirs.append(child)
    return dirs


def discover_domains(root: Path) -> dict[str, LoadedDomain]:
    """Load every domain under ``root`` keyed by domain name.

    A directory whose ``domain.yaml`` fails to load is skipped with a logged
    warning; the caller sees the surviving domains. Use
    :func:`load_domain_dir` directly to surface the error.
    """
    domains: dict[str, LoadedDomain] = {}
    for domain_dir in find_domain_dirs(root):
        try:
            loaded = load_domain_dir(domain_dir)
        except DomainLoadError as exc:
            logger.warning("Skipping domain at %s: %s", domain_dir, exc)
            continue
        domains[loaded.name] = loaded
    return domains


# --------------------------------------------------------------------------
# Scope resolution
# --------------------------------------------------------------------------


@dataclass
class DomainScope:
    """One domain root touched by a validated path.

    Attributes:
        root: Directory whose direct children are the sibling domains.
        label: ``root`` relative to the validated path (``""`` when they are
            the same directory, or when the path sits inside the root). Used
            to tell roots apart when one path covers several.
        domains: Every domain in ``root`` -- the set rules run against.
        in_scope: Directory names of the domains the path covers. A name here
            that is missing from ``domains`` failed to load.
        table: When the path is a single table inside a domain, that table's
            ``table_name``; findings narrow to it.
        covers_root: True when the path is at or above ``root``, so a domain
            removed from the root is also within what the path covers.

    """

    root: Path
    label: str
    domains: dict[str, LoadedDomain]
    in_scope: set[str]
    table: str | None = None
    covers_root: bool = False


def _owning_domain_dir(start: Path) -> Path | None:
    """Nearest directory at or above ``start`` holding a ``domain.yaml``.

    The search stops at a repository root (a directory containing ``.git``)
    so a stray ``domain.yaml`` far up the filesystem is never adopted.
    """
    current = start
    while True:
        if (current / DOMAIN_FILENAME).is_file():
            return current
        if (current / ".git").exists() or current.parent == current:
            return None
        current = current.parent


def resolve_domain_scopes(path: Path) -> list[DomainScope]:
    """Find the domain roots a validated ``path`` involves.

    * ``path`` is inside a domain (the domain directory itself, a table in it,
      or a file in it): one scope whose root is the domain's parent, covering
      just that domain (and just that table, when ``path`` is one table).
    * Otherwise every ``domain.yaml`` directory beneath ``path`` is found
      (hidden and vendored directories skipped, nested ``domain.yaml`` inside
      a domain ignored), grouped by parent into one scope per domain root.

    Returns an empty list when no ``domain.yaml`` is involved.
    """
    path = Path(path).resolve()
    start = path if path.is_dir() else path.parent

    owner = _owning_domain_dir(start)
    if owner is not None:
        domains = discover_domains(owner.parent)
        loaded = domains.get(owner.name)
        table = loaded.table_at(path) if loaded and path != owner else None
        return [
            DomainScope(
                root=owner.parent,
                label="",
                domains=domains,
                in_scope={owner.name},
                table=table,
            )
        ]

    by_root: dict[Path, set[str]] = {}
    for current, dirnames, filenames in os.walk(start):
        dirnames[:] = sorted(d for d in dirnames if not is_pruned_dir(d))
        here = Path(current)
        if DOMAIN_FILENAME in filenames:
            by_root.setdefault(here.parent, set()).add(here.name)
            dirnames[:] = []  # a domain.yaml nested inside a domain is ignored
        elif TABLE_FILENAME in filenames:
            dirnames[:] = []

    scopes: list[DomainScope] = []
    for root in sorted(by_root):
        rel = root.relative_to(start) if root != start else Path()
        scopes.append(
            DomainScope(
                root=root,
                label="" if rel == Path() else rel.as_posix(),
                domains=discover_domains(root),
                in_scope=by_root[root],
                covers_root=True,
            )
        )
    return scopes


__all__ = [
    "DomainScope",
    "LoadedDomain",
    "discover_domains",
    "find_domain_dirs",
    "is_pruned_dir",
    "iter_table_dirs",
    "load_domain_dir",
    "resolve_domain_scopes",
]
