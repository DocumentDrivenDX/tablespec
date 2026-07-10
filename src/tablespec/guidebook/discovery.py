"""Flat UMF discovery for the guidebook.

Replaces pulseflow's pipeline-aware ``PipelineDiscovery`` with a simple
recursive walk over a root directory. A "discovered UMF" is a split directory
(contains ``table.yaml``), a single ``*.umf.json`` artifact, or a single
``*.umf.yaml`` artifact.

``*.umf.yaml`` is the artifact format the compile/e2e pipeline emits (see
``e2e.manifest`` and ``core.selection``, which globs the same pattern), so the
guidebook must read it or it cannot render its own pipeline's output. Those
whole-document YAML files are deliberately NOT auto-detected by
``UMFLoader.load`` — that stance is intentional and left untouched here.
Instead this module loads them through the public ``load_umf_from_yaml``,
exactly as ``core.selection`` does.

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

from tablespec.models.umf import load_umf_from_yaml
from tablespec.umf_loader import UMFLoader

logger = logging.getLogger(__name__)

# Whole-document YAML UMFs emitted by the compile pipeline.
UMF_YAML_SUFFIX = ".umf.yaml"


def load_discovered_umf(path: Path):
    """Load a UMF from any guidebook-discoverable path.

    Dispatches on shape: whole-document ``*.umf.yaml`` goes through the public
    ``load_umf_from_yaml``; split dirs and ``*.umf.json`` go through
    ``UMFLoader.load``. Kept in one place so discovery and rendering can never
    disagree about how a given path is read.
    """
    path = Path(path)
    if path.is_file() and path.name.endswith(UMF_YAML_SUFFIX):
        return load_umf_from_yaml(path)
    return UMFLoader().load(path)


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

    Finds split-format directories (those containing a ``table.yaml``), JSON
    artifacts (``*.umf.json``), and whole-document YAML artifacts
    (``*.umf.yaml``, what the compile pipeline emits). Loads each to read its
    ``table_name``. A UMF that fails to load is logged and skipped.

    Duplicate ``(group, table)`` pairs would collide on the same output path;
    the first wins and subsequent duplicates are logged and skipped. Candidate
    order is split dirs, then JSON, then YAML — so when a table exists in more
    than one format the richer format wins deterministically.

    Returns the discovered UMFs sorted by ``(group, table)`` for stable output.
    """
    root = Path(root).resolve()

    # Split dirs: the parent of every table.yaml.
    candidates: list[Path] = sorted({p.parent for p in root.rglob("table.yaml")})
    # JSON artifacts.
    candidates += sorted(root.rglob("*.umf.json"))
    # Whole-document YAML artifacts (compile-pipeline output).
    candidates += sorted(root.rglob(f"*{UMF_YAML_SUFFIX}"))

    seen: set[tuple[str, str]] = set()
    discovered: list[DiscoveredUmf] = []
    for path in candidates:
        try:
            umf = load_discovered_umf(path)
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
