# SPDX-License-Identifier: MIT OR Apache-2.0
"""dbt rendering of ``ingestion.mode: change_tracking``.

Shared by the single-table and DAG emitters so both write change feeds the
same way:

* ``strategy: rebuild`` -> a ``table`` model over the live state recomputed
  from the raw source's full history (the newest baseline supersedes).
* ``strategy: merge`` -> an ``incremental`` ``merge`` model on the primary key
  that upserts each key's latest non-delete row from the batch, plus a
  ``post_hook`` that deletes keys whose latest operation in the batch is a
  delete. dbt's merge strategy cannot delete, hence the hook; it is plain
  ``DELETE ... WHERE key IN (...)`` so it runs on any adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tablespec.dbt.materialization import Materialization

if TYPE_CHECKING:
    from tablespec.schemas.ingest_generator import IngestSelect


def change_tracking_materialization(
    ingest: IngestSelect, source: str
) -> Materialization:
    """The model's materialization (with its delete hook for ``merge``)."""
    feed = ingest.feed()
    if feed.strategy == "rebuild":
        return Materialization(strategy="table")
    return Materialization(
        strategy="incremental",
        incremental_strategy="merge",
        unique_key=tuple(ingest.primary_key),
        post_hook=_delete_hook_sql(ingest, source),
    )


def change_tracking_body(ingest: IngestSelect, source: str) -> str:
    """The model's SELECT over *source*."""
    feed = ingest.feed()
    if feed.strategy == "rebuild":
        return (
            "-- change_tracking (rebuild): live state from the full raw history;\n"
            f"-- the newest baseline (by {feed.delivery_column}) supersedes earlier rows.\n"
            f"SELECT\n{ingest.select_block}\n"
            f"FROM (\n{ingest.change_state_sql(source)}\n) AS src_raw"
        )
    return (
        "-- change_tracking (merge): dbt MERGEs each key's latest non-delete row;\n"
        "-- the post_hook deletes keys whose latest operation is a delete.\n"
        f"SELECT\n{ingest.select_block}\n"
        f"FROM (\n{ingest.change_batch_sql(source)}\n) AS src_raw\n"
        f"WHERE NOT {feed.is_delete('src_raw.' + feed.OPERATION_ALIAS)}"
    )


def _delete_hook_sql(ingest: IngestSelect, source: str) -> str:
    feed = ingest.feed()
    keys = ingest.primary_key
    target = keys[0] if len(keys) == 1 else f"({', '.join(keys)})"
    casts = ", ".join(ingest.key_casts)
    return (
        f"DELETE FROM {{{{ this }}}} WHERE {target} IN ("
        f"SELECT {casts} FROM ({ingest.change_batch_sql(source).strip()}) AS d "
        f"WHERE {feed.is_delete('d.' + feed.OPERATION_ALIAS)})"
    )


def render_post_hook_arg(sql: str) -> str:
    """``post_hook="..."`` for a dbt config block.

    Jinja string literals decode backslash escapes, so backslashes in *sql*
    (e.g. the ``'^\\\\$'`` currency-strip regex) are doubled and double quotes
    escaped; the hook then renders back to exactly *sql*.
    """
    escaped = " ".join(sql.split()).replace("\\", "\\\\").replace('"', '\\"')
    return f'        post_hook="{escaped}",'


__all__ = [
    "change_tracking_body",
    "change_tracking_materialization",
    "render_post_hook_arg",
]
