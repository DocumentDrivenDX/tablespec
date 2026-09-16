"""Discover domains (bounded contexts) under a root directory.

A domain is any directory that contains a ``domain.yaml`` (see
:mod:`tablespec.models.domain`). Its tables are the split-format UMF
directories (``table.yaml``) and ``*.umf.json`` files found beneath it.
Discovery is one level deep by design: a domain directory is the unit the
guidebook already treats as a *group* and the qualifier ``domain.table``
references use, so nesting domains inside domains would make the qualifier
ambiguous.

This module is the shared loader for the domain validator and the guidebook
domain map. It never renders or validates; it only reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
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


@dataclass
class LoadedDomain:
    """A domain directory with its metadata, glossary, and tables loaded."""

    path: Path
    metadata: DomainMetadata
    glossary: Glossary | None = None
    tables: dict[str, UMF] = field(default_factory=dict)
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


def _load_any_umf(path: Path) -> UMF:
    if path.is_file() and path.name.endswith(UMF_YAML_SUFFIX):
        return load_umf_from_yaml(path)
    return UMFLoader().load(path)


def _table_candidates(domain_dir: Path) -> list[Path]:
    candidates: list[Path] = sorted({p.parent for p in domain_dir.rglob("table.yaml")})
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


__all__ = [
    "LoadedDomain",
    "discover_domains",
    "find_domain_dirs",
    "load_domain_dir",
]
