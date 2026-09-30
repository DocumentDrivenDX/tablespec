"""Pluggable UMF and source-location providers for the lineage builder.

Tables are addressed as ``(group, table)``, where the group is the UMF's
parent subfolder relative to the discovery root (``""`` at the root) — the
same grouping the guidebook uses (ADR-018). ``DiscoveredUMFProvider`` reads
any directory :func:`tablespec.guidebook.discovery.discover_umfs` understands;
projects with other storage implement the :class:`UMFProvider` protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from tablespec.lineage.models import SourceLocation
from tablespec.models.umf import DelimitedSource, JdbcSource

if TYPE_CHECKING:
    from tablespec.models.umf import UMF


class UMFProvider(Protocol):
    """Resolves UMFs by group and table name."""

    def get_umf(self, group: str, table: str) -> UMF | None:
        """Return the table's UMF, or None when it does not exist."""
        ...

    def list_tables(self, group: str) -> list[str]:
        """Return the table names in a group."""
        ...


class LocationResolver(Protocol):
    """Resolves where a source table's data is read from."""

    def resolve(self, group: str, umf: UMF) -> SourceLocation | None:
        """Return the location of a source (non-generated) table, or None."""
        ...


def effective_source_directory(umf: UMF) -> str:
    """Return the folder a delimited table's files are read from (defaults to the table name)."""
    source = umf.effective_source()
    if isinstance(source, DelimitedSource) and source.source_directory:
        return source.source_directory
    return umf.table_name


class DiscoveredUMFProvider:
    """Serve UMFs found by guidebook discovery under ``root``."""

    def __init__(self, root: Path) -> None:
        # Imported here: tablespec.guidebook imports this package.
        from tablespec.guidebook.discovery import discover_umfs  # noqa: PLC0415

        self.root = Path(root).resolve()
        self._paths = {(d.group, d.table): d.path for d in discover_umfs(self.root)}
        self._umfs: dict[tuple[str, str], UMF | None] = {}

    def list_groups(self) -> list[str]:
        """Return every group (``""`` for UMFs at the root)."""
        return sorted({group for group, _ in self._paths})

    def list_tables(self, group: str) -> list[str]:
        return sorted(table for g, table in self._paths if g == group)

    def get_umf(self, group: str, table: str) -> UMF | None:
        from tablespec.guidebook.discovery import load_discovered_umf  # noqa: PLC0415

        key = (group, table)
        if key not in self._umfs:
            path = self._paths.get(key)
            self._umfs[key] = load_discovered_umf(path) if path else None
        return self._umfs[key]


class SourceLocationResolver:
    """Default resolver: where ``umf.effective_source()`` reads from.

    Delimited sources resolve to ``source.path`` or their folder
    (``source_directory``, else the table name); parquet/json to their path;
    JDBC to its URL and table. The result doubles as the "source system".
    """

    def resolve(self, group: str, umf: UMF) -> SourceLocation | None:
        if umf.table_type == "generated":
            return None
        source = umf.effective_source()
        if isinstance(source, JdbcSource):
            system = source.url
            path = f"{source.url} {source.dbtable}" if source.dbtable else source.url
        elif isinstance(source, DelimitedSource):
            system = source.path or effective_source_directory(umf)
            path = system
        else:
            system = source.path or umf.table_name
            path = system
        return SourceLocation(source_system=system, path=path)
