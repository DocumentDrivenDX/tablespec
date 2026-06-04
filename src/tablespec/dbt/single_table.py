"""Generate a dbt(+DuckDB) project that ingests a raw landing table per a UMF spec.

This is the second emitter of the raw->ingest design. It shares the cast SELECT and
dedup-latest window with the committed Databricks artifact via
:func:`tablespec.schemas.ingest_generator.build_ingest_select`; the two emitters
differ only in *packaging* and *write strategy*.

dbt owns the write -- the model body never hand-writes a MERGE/INSERT. The write is
expressed entirely through the model ``config`` (derived from ``ingestion.mode`` +
``primary_key``):

  * incremental + primary_key  -> ``materialized='incremental'``,
                                  ``incremental_strategy='merge'``, ``unique_key=[...]``
  * incremental, no primary_key -> ``materialized='incremental'`` (append; no key)
  * snapshot                    -> ``materialized='table'`` (full drop/reload; this is a
                                    plain table rebuild, NOT dbt's SCD2 snapshot block)

The model reads from a dbt ``source`` (the all-STRING ``raw_<table>`` landing table)
and emits the typed cast columns. For the incremental+pk case the model body applies
the shared dedup-latest window so the newest row per key wins *within the current
batch*, exactly mirroring the Spark baseline.

:func:`generate_dbt_project` returns a ``{relative_path: file_contents}`` mapping (and
optionally writes those files to ``out_dir``), so it can be unit-tested as golden text
without touching the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tablespec.core.schema_facts import (
    accepted_values_tests,
    column_contracts,
    relationship_tests,
)
from tablespec.dbt.contracts import (
    render_column_contract,
    render_contract_config_arg,
)
from tablespec.dbt.schema_tests import render_tests_for_column
from tablespec.models.umf import UMF
from tablespec.schemas.ingest_generator import (
    IngestSelect,
    build_ingest_select,
)


def _model_config(ingest: IngestSelect) -> str:
    """Render the dbt ``{{ config(...) }}`` block for the table's write strategy.

    dbt owns the write -- this config is the entire write contract. The block also
    opts the model into an ENFORCED data contract (``contract={'enforced': True}``)
    so the adapter validates the materialized relation against the per-column
    ``data_type`` + ``constraints:`` declared in ``schema.yml``.

    An incremental model with an enforced contract MUST pin ``on_schema_change``
    (dbt rejects the default ``ignore``); we use ``'fail'`` so a column-set drift
    in the SELECT surfaces loudly rather than silently mutating the relation.
    """
    contract = render_contract_config_arg()
    on_change = "        on_schema_change='fail',"
    if ingest.mode == "incremental" and ingest.primary_key:
        # Upsert: dbt emits a MERGE on the unique key.
        keys = ", ".join(f'"{k}"' for k in ingest.primary_key)
        return (
            "{{\n"
            "    config(\n"
            "        materialized='incremental',\n"
            "        incremental_strategy='merge',\n"
            f"        unique_key=[{keys}],\n"
            f"{on_change}\n"
            f"{contract}\n"
            "    )\n"
            "}}"
        )
    if ingest.mode == "incremental":
        # Keyless append: dbt's default incremental strategy blindly inserts the
        # batch; duplicate rows accumulate on re-ingest (matches the Spark baseline).
        return (
            "{{\n"
            "    config(\n"
            "        materialized='incremental',\n"
            f"{on_change}\n"
            f"{contract}\n"
            "    )\n"
            "}}"
        )
    # snapshot -> full drop/reload as a plain table rebuild (NOT dbt's SCD2 snapshot).
    return f"{{{{\n    config(\n        materialized='table',\n{contract}\n    )\n}}}}"


def _model_sql(table: str, ingest: IngestSelect) -> str:
    """Render the dbt model SQL for *table*.

    The body is the shared cast SELECT over the raw source. For incremental+pk it
    runs the shared dedup-latest window so the newest row per key wins within the
    batch; dbt then MERGEs that deduped set into the target.
    """
    config = _model_config(ingest)
    source = f"{{{{ source('raw', 'raw_{table}') }}}}"

    if ingest.has_dedup:
        # incremental + pk: dbt MERGEs on the unique key; the model body dedups the
        # current batch (newest row per key wins) so the merge upserts one row/key.
        note = (
            "-- incremental + primary_key: dbt MERGEs on unique_key.\n"
            "-- The dedup-latest window keeps the newest row per key in the batch.\n"
        )
        body = (
            f"{note}SELECT\n"
            f"{ingest.select_block}\n"
            "FROM (\n"
            f"{ingest.dedup_window_sql(source)}\n"
            ") AS src_raw"
        )
    elif ingest.mode == "incremental":
        # keyless incremental: dbt blindly appends the current source rows. The
        # write contract is that raw_<table> holds ONE batch per run (it is replaced
        # per batch upstream); re-running against accumulated raw would re-append and
        # duplicate. This mirrors the Spark artifact's blind INSERT INTO branch.
        note = (
            "-- WARNING: no primary_key + incremental -> blind append (no dedup).\n"
            "-- Contract: raw source holds ONE batch per run; duplicates accumulate\n"
            "-- on re-ingest of the same rows (matches the Spark INSERT INTO branch).\n"
        )
        body = f"{note}SELECT\n{ingest.select_block}\nFROM {source}"
    else:
        # snapshot: full table rebuild from the current source each run.
        note = "-- snapshot: full drop/reload (materialized table rebuild).\n"
        body = f"{note}SELECT\n{ingest.select_block}\nFROM {source}"

    return f"{config}\n\n{body}\n"


def _related_resolver(related: list[UMF] | None, self_table: str):
    """A ``resolve_target`` for ``core.schema_facts`` over the single-table set.

    Each table in the single-table path is emitted as a model named after its own
    ``table_name`` (no ``ingested_``/``gold_`` prefix). A FK target resolves to
    that bare model name iff the referenced table is the table itself or appears
    in ``related``; otherwise it is unresolvable and the test is SKIPPED (no
    ``ref()`` to a missing model -- the AC1.2/AC1.5 skip-when-unresolvable rule).
    """
    known = {self_table}
    for u in related or []:
        known.add(u.table_name)

    def resolve(table: str) -> str | None:
        return table if table in known else None

    return resolve


def _schema_yml(
    umf_data: dict[str, Any],
    table: str,
    ingest: IngestSelect,
    related: list[UMF] | None,
    *,
    dialect: str,
) -> str:
    """Render ``models/schema.yml`` with the model contract + column tests.

    The model declares an ENFORCED data contract: every column carries a
    ``data_type`` (the adapter SQL type for its UMF type) and, when non-nullable,
    a ``not_null`` ``constraints:`` entry -- both enforced by the adapter at
    ``dbt build``. On top of the contract, columns carry generic ``data_tests:``:

    * ``unique`` for single-column primary keys and any single-column
      ``unique_constraints`` entry. (Composite uniqueness is left to the merge key
      and not asserted as a per-column test.)
    * ``relationships`` for each non-cross-pipeline FK whose target resolves in the
      ``related`` set (skip-when-unresolvable; composite FKs -> one test per
      scalar column).
    * ``accepted_values`` for each column carrying an
      ``expect_column_values_to_be_in_set`` expectation.

    The ``not_null`` rule is expressed once -- as the contract constraint -- not
    also as a generic ``not_null`` data test (the adapter enforces the constraint
    at build; a duplicate generic test would be redundant).
    """
    cols: list[dict[str, Any]] = umf_data["columns"]
    pk = ingest.primary_key
    unique_constraints: list[Any] = umf_data.get("unique_constraints") or []

    # Collect the set of columns that should carry a `unique` test.
    unique_cols: set[str] = set()
    if len(pk) == 1:
        unique_cols.add(pk[0])
    for uc in unique_constraints:
        # A constraint may be a bare column name or a single-column list.
        if isinstance(uc, str):
            unique_cols.add(uc)
        elif isinstance(uc, list) and len(uc) == 1:
            unique_cols.add(uc[0])

    resolver = _related_resolver(related, table)
    rel_by_col: dict[str, list] = {}
    for t in relationship_tests(umf_data, resolver):
        rel_by_col.setdefault(t.column, []).append(t)
    av_by_col: dict[str, list] = {}
    for t in accepted_values_tests(umf_data):
        av_by_col.setdefault(t.column, []).append(t)

    contracts = {c.name: c for c in column_contracts(umf_data)}

    lines: list[str] = [
        "version: 2",
        "",
        "models:",
        f"  - name: {table}",
    ]
    description = umf_data.get("description")
    if description:
        lines.append(f"    description: {_yaml_scalar(description)}")
    lines.append("    config:")
    lines.append("      contract:")
    lines.append("        enforced: true")
    lines.append("    columns:")

    for col in cols:
        name = col["name"]
        is_unique = name in unique_cols
        extra = rel_by_col.get(name, []) + av_by_col.get(name, [])
        # Contract: data_type (+ not_null constraint) for the column.
        contract = contracts[name]
        lines.extend(render_column_contract(contract, dialect=dialect))
        # Generic data tests layered on top of the contract (unique / relationships
        # / accepted_values). not_null is the contract constraint, not a data test.
        if is_unique or extra:
            lines.append("        data_tests:")
            if is_unique:
                lines.append("          - unique")
            for t in extra:
                # The ``data_tests:`` header is already present; render the entry
                # lines only (drop render_tests_for_column's header line).
                lines.extend(render_tests_for_column([t])[1:])

    return "\n".join(lines) + "\n"


def _sources_yml(table: str) -> str:
    """Render ``models/sources.yml`` declaring the raw landing table as a source."""
    return (
        "version: 2\n"
        "\n"
        "sources:\n"
        "  - name: raw\n"
        "    schema: main\n"
        "    tables:\n"
        f"      - name: raw_{table}\n"
    )


def _dbt_project_yml(project_name: str) -> str:
    """Render ``dbt_project.yml`` for the generated project."""
    return (
        f"name: '{project_name}'\n"
        "version: '1.0.0'\n"
        "config-version: 2\n"
        "\n"
        f"profile: '{project_name}'\n"
        "\n"
        'model-paths: ["models"]\n'
        'target-path: "target"\n'
        'clean-targets: ["target", "dbt_packages"]\n'
    )


def _profiles_yml(project_name: str) -> str:
    """Render a DuckDB ``profiles.yml`` template.

    The ``path`` is a placeholder; runners (and the parity test) override it via the
    ``DBT_DUCKDB_PATH`` env var or by writing a concrete profiles.yml.

    The session is pinned to UTC so TIMESTAMP rendering is host-timezone independent
    and matches the Spark baseline (which also pins the whole stack to UTC). Without
    this, no-format / timezone-bearing timestamp parsing could differ across hosts.
    """
    return (
        f"{project_name}:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        "      path: \"{{ env_var('DBT_DUCKDB_PATH', 'ingest.duckdb') }}\"\n"
        "      threads: 1\n"
        "      settings:\n"
        "        TimeZone: 'UTC'\n"
    )


def _yaml_scalar(value: str) -> str:
    """Quote a scalar for safe single-line YAML emission."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def generate_dbt_project(
    umf_data: dict[str, Any],
    *,
    dialect: str = "duckdb",
    out_dir: str | Path | None = None,
    project_name: str = "tablespec_ingest",
    related: list[UMF] | None = None,
) -> dict[str, str]:
    """Generate a dbt(+DuckDB) project for a UMF table's raw->ingest transform.

    Reuses :func:`build_ingest_select` for the model body, so the cast logic and
    dedup window are identical to the committed Databricks artifact. dbt owns the
    write: the model ``config`` (not hand-written SQL) selects merge / append /
    table-rebuild based on ``ingestion.mode`` + ``primary_key``.

    Args:
    ----
        umf_data: UMF table data (e.g. ``umf.model_dump(exclude_none=True)``).
        dialect: SQL dialect for the cast expressions; defaults to ``"duckdb"``.
        out_dir: If given, the returned files are also written under this directory.
        project_name: dbt project + profile name.
        related: Optional sibling tables (as :class:`UMF`) emitted alongside this
            one. A FK ``relationships`` test is emitted only when its target table
            is this table or appears in ``related`` (skip-when-unresolvable); with
            ``related=None`` only self-referential FKs resolve and all others are
            skipped (never a ``ref()`` to a missing model).

    Returns:
    -------
        A mapping of ``{relative_path: file_contents}`` for the whole project.

    """
    table = umf_data["table_name"]
    ingest = build_ingest_select(umf_data, dialect=dialect)

    files: dict[str, str] = {
        "dbt_project.yml": _dbt_project_yml(project_name),
        "profiles.yml": _profiles_yml(project_name),
        "models/sources.yml": _sources_yml(table),
        "models/schema.yml": _schema_yml(
            umf_data, table, ingest, related, dialect=dialect
        ),
        f"models/{table}.sql": _model_sql(table, ingest),
    }

    if out_dir is not None:
        base = Path(out_dir)
        for rel, content in files.items():
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

    return files
