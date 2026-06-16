"""Pre-built search index for the guidebook.

Emits a flat ``search_index.json`` next to the generated HTML — one entry per
table and one per column. Generation-time only. URLs are relative so the index
works opened from ``file://`` or served by a plain static server.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from tablespec.umf_loader import UMFLoader

if TYPE_CHECKING:
    from pathlib import Path

    from tablespec.guidebook.discovery import DiscoveredUmf

logger = logging.getLogger(__name__)


def _table_url(group: str, table: str) -> str:
    seg = f"{group}/" if group else ""
    return f"./{seg}{table}.html"


def _column_url(group: str, table: str, column: str) -> str:
    return f"{_table_url(group, table)}#col-{column}"


def build_search_index(output_dir: Path, discovered: list[DiscoveredUmf]) -> Path:
    """Write ``search_index.json`` under ``output_dir``. Returns the path."""
    loader = UMFLoader()
    entries: list[dict[str, Any]] = []

    for unit in discovered:
        try:
            umf = loader.load(unit.path)
        except Exception as exc:
            logger.warning("Skipping %s in search index: %s", unit.path, exc)
            continue

        group = unit.group
        table = unit.table
        description = getattr(umf, "description", None) or ""
        label_prefix = f"{group} " if group else ""
        entries.append(
            {
                "group": group,
                "table": table,
                "column": None,
                "description": description,
                "url": _table_url(group, table),
                "haystack": f"{label_prefix}{table} {description}".lower(),
            }
        )

        for column in umf.columns:
            col_desc = column.description or ""
            entries.append(
                {
                    "group": group,
                    "table": table,
                    "column": column.name,
                    "description": col_desc,
                    "url": _column_url(group, table, column.name),
                    "haystack": f"{label_prefix}{table} {column.name} {col_desc}".lower(),
                }
            )

    output_path = output_dir / "search_index.json"
    output_path.write_text(json.dumps(entries), encoding="utf-8")
    return output_path
