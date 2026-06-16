"""Flat UMF discovery for the guidebook.

Replaces pulseflow's pipeline-aware ``PipelineDiscovery`` with a simple
recursive walk over a root directory. A "discovered UMF" is either a split
directory (contains ``table.yaml``) or a single ``*.umf.json`` artifact.

Each discovered UMF carries a ``group`` — its parent subdirectory relative to
the root, or ``""`` when it sits at the root. The group becomes the output
subfolder (``<group>/<table>.html``) and the qualifier used in lineage keys
(``group.table.column``). When every UMF is at the root the guidebook is flat:
no per-group index, output files written directly under the output dir.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from tablespec.umf_loader import UMFLoader

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredUmf:
    """One UMF located under a discovery root.

    Attributes:
        path: Path to pass to ``UMFLoader.load`` (split dir or JSON file).
        group: Parent subdirectory relative to the root, or ``""`` at root.
        table: ``umf.table_name`` — used as the output filename slug.

    """

    path: Path
    group: str
    table: str


def _group_for(path: Path, root: Path) -> str:
    """Return the group: the directory containing the UMF, relative to ``root``.

    The "container" is the parent of the split dir, or the parent of the JSON
    file. For a split dir ``root/orders`` the container is ``root`` -> group
    ``""``. For ``root/sales/orders`` it is ``root/sales`` -> group ``sales``.
    For a JSON file ``root/sales/orders.umf.json`` it is ``root/sales`` ->
    ``sales``; at the root -> ``""``. Deeper nesting yields a multi-segment
    group like ``a/b`` (a relative POSIX path).
    """
    # Split dir -> its parent; JSON file -> its parent.
    container = path.parent
    try:
        rel = container.relative_to(root)
    except ValueError:
        return ""
    # rel == Path('.') means the container is the root itself.
    return "" if rel == Path() else rel.as_posix()


def discover_umfs(root: Path) -> list[DiscoveredUmf]:
    """Recursively discover every UMF under ``root``.

    Finds split-format directories (those containing a ``table.yaml``) and
    JSON artifacts (``*.umf.json``). Loads each to read its ``table_name``.
    A UMF that fails to load is logged and skipped.

    Duplicate ``(group, table)`` pairs would collide on the same output path;
    the first wins and subsequent duplicates are logged and skipped.

    Returns the discovered UMFs sorted by ``(group, table)`` for stable output.
    """
    root = Path(root).resolve()
    loader = UMFLoader()

    # Split dirs: the parent of every table.yaml.
    candidates: list[Path] = sorted({p.parent for p in root.rglob("table.yaml")})
    # JSON artifacts.
    candidates += sorted(root.rglob("*.umf.json"))

    seen: set[tuple[str, str]] = set()
    discovered: list[DiscoveredUmf] = []
    for path in candidates:
        try:
            umf = loader.load(path)
        except Exception as exc:
            logger.warning("Skipping %s during discovery: %s", path, exc)
            continue

        group = _group_for(path, root)
        table = umf.table_name
        key = (group, table)
        if key in seen:
            logger.warning(
                "Duplicate UMF (group=%r, table=%r) at %s — keeping the first, skipping this one.",
                group,
                table,
                path,
            )
            continue
        seen.add(key)
        discovered.append(DiscoveredUmf(path=path, group=group, table=table))

    discovered.sort(key=lambda d: (d.group, d.table))
    return discovered
