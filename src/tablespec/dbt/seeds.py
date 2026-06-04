"""Emit the EXISTING ``SampleDataGenerator`` output as dbt *seeds* (item 4).

The generator (``tablespec.sample_data.engine.SampleDataGenerator``) WRITES real
generated rows into an ``output_dir`` as a delimited text file per table (the UMF
``file_format.delimiter``, default ``|``), with a filename derived from the UMF
filename pattern -- not necessarily ``<table>.txt`` -- and a header that uses each
column's ``canonical_name`` when present. It does NOT return CSV text.

This module is the SEED EMITTER: it does NOT re-implement generation. It

  1. resolves and reads the already-generated file for each table from
     ``output_dir`` (the generator always leaves a ``<table>.txt`` name -- the
     real file or a symlink to the pattern-named file -- so that is the stable
     handle), parsing it with the UMF delimiter and mapping the
     ``canonical_name`` header back to the UMF column ``name``; and
  2. NORMALIZES the SAME rows/values into a dbt-seed-compatible
     ``seeds/<table>.csv`` (comma-delimited, header = the UMF column names), and
  3. derives a ``seeds:`` config block (``column_types`` per table from the UMF
     contract facts) that the caller splices into ``dbt_project.yml``.

The project generators (``generate_dbt_project`` / ``generate_dbt_dag_project``)
gain NO seed coupling -- seeding is a SEPARATE function the caller invokes, so the
generators stay unchanged and the direct-artifact path is untouched.

Encapsulation: this is pure-Python text emission fed by ``tablespec.core``
(``column_contracts``) and the public UMF model. The import direction is the
allowed one -- ``tablespec.dbt`` -> ``tablespec.core`` (never the reverse) -- and
it imports NO ``dbt`` package (importing this module pulls in no dbt-core, so the
``[dbt]`` extra is only needed to RUN the generated project). The ``sample_data``
engine is the GENERATOR; this module only consumes its on-disk output, so it does
not import the engine either.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tablespec.core.schema_facts import column_contracts
from tablespec.dbt.contracts import contract_sql_type
from tablespec.models.umf import UMF


class SeedEmitterError(ValueError):
    """Raised when a table's generated sample file cannot be located / read."""


def _umf_dict(umf: UMF) -> dict[str, Any]:
    return umf.model_dump(exclude_none=True)


def _data_columns(umf_data: dict[str, Any]) -> list[dict[str, Any]]:
    """The columns the generator actually wrote (``source`` defaults to ``data``).

    Mirrors ``SampleDataGenerator.save_data``: only ``source == "data"`` columns
    land in the generated file; filename-sourced / metadata columns are added
    downstream and are not present in the seed.
    """
    return [
        col
        for col in umf_data.get("columns") or []
        if col.get("source", "data") == "data"
    ]


def _delimiter(umf_data: dict[str, Any]) -> str:
    """The generator's output delimiter (UMF ``file_format.delimiter``, default ``|``)."""
    file_format = umf_data.get("file_format") or {}
    return file_format.get("delimiter", "|")


def _resolve_generated_file(output_dir: Path, table_name: str) -> Path:
    """Resolve the generated file for *table_name* under *output_dir*.

    ``SampleDataGenerator`` always leaves a ``<table>.txt`` entry -- either the
    real output file (when no filename pattern applies) or a symlink to the
    pattern-named file -- so ``<table>.txt`` is the stable, pattern-independent
    handle. Resolving the symlink yields the bytes regardless of the on-disk
    pattern name.
    """
    candidate = output_dir / f"{table_name}.txt"
    if candidate.exists():
        return candidate.resolve()
    msg = (
        f"No generated sample file for table {table_name!r} under {output_dir} "
        f"(expected {candidate.name}; run SampleDataGenerator first)."
    )
    raise SeedEmitterError(msg)


def _header_to_name(umf_data: dict[str, Any]) -> dict[str, str]:
    """Map the GENERATED header label back to the UMF column ``name``.

    The generator writes ``canonical_name`` as the header when present, else the
    column ``name``; this inverts that so the normalized seed header is the UMF
    column ``name`` (which the ``column_types`` / contract facts key on).
    """
    mapping: dict[str, str] = {}
    for col in _data_columns(umf_data):
        name = col["name"]
        header = col.get("canonical_name") or name
        mapping[header] = name
    return mapping


def _read_generated_rows(
    path: Path, umf_data: dict[str, Any]
) -> tuple[list[str], list[dict[str, str]]]:
    """Read the generated delimited file into (column_names, row dicts).

    Returns the UMF column ``name`` order (data columns, generator write order)
    and one dict per data row keyed by UMF column name. Raises if a generated
    header label does not correspond to a known UMF column.
    """
    delimiter = _delimiter(umf_data)
    header_to_name = _header_to_name(umf_data)
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []

    names_in_order: list[str] = []
    for header in headers:
        if header not in header_to_name:
            msg = (
                f"Generated file {path} has a column {header!r} not present in the "
                f"UMF data columns (known headers: {sorted(header_to_name)})."
            )
            raise SeedEmitterError(msg)
        names_in_order.append(header_to_name[header])

    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({header_to_name[h]: (raw.get(h) or "") for h in headers})
    return names_in_order, rows


def _normalize_csv(column_names: list[str], rows: list[dict[str, str]]) -> str:
    """Re-encode (column_names, rows) as a comma-delimited dbt-loadable CSV.

    Header = the UMF column names; one row per generated record; values carried
    through verbatim (the SAME values, re-encoded). Uses ``\\n`` line endings and
    RFC-4180 quoting so embedded delimiters survive.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=column_names, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in column_names})
    return buf.getvalue()


def seed_column_types(umf: UMF, *, dialect: str = "duckdb") -> dict[str, str]:
    """Derive the dbt ``column_types`` mapping for *umf*'s seed.

    Maps each generated data column's logical UMF type to its adapter SQL type
    (the SAME mapping the enforced model contract uses, via
    :func:`tablespec.dbt.contracts.contract_sql_type`), so a loaded seed carries
    the declared types (e.g. ``{member_id: INTEGER, amount: 'DECIMAL(18,2)'}``).
    Only ``source == "data"`` columns appear (those are what the generator wrote).
    """
    umf_data = _umf_dict(umf)
    data_names = {col["name"] for col in _data_columns(umf_data)}
    types: dict[str, str] = {}
    for contract in column_contracts(umf_data):
        if contract.name in data_names:
            types[contract.name] = contract_sql_type(contract, dialect=dialect)
    return types


@dataclass(frozen=True)
class SeedArtifacts:
    """The output of :func:`emit_seeds`: seed files + per-table ``column_types``.

    Attributes:
        files: ``{relative_path: contents}`` -- one ``seeds/<table>.csv`` per
            table (comma-delimited, header = UMF column names).
        column_types: ``{table_name: {column: adapter_sql_type}}`` for the
            ``seeds:`` config block.
    """

    files: dict[str, str]
    column_types: dict[str, dict[str, str]]


def emit_seeds(
    umfs: list[UMF],
    output_dir: str | Path,
    *,
    dialect: str = "duckdb",
) -> SeedArtifacts:
    """Emit dbt seeds from a generator's *output_dir* for the given UMF set.

    For each UMF, reads the already-generated sample file from *output_dir*
    (resolving the stable ``<table>.txt`` handle / symlink), parses it with the
    UMF delimiter, maps the ``canonical_name`` header back to the UMF column
    ``name``, and re-encodes the SAME rows as ``seeds/<table>.csv``
    (comma-delimited). Also derives the per-table ``column_types`` from the UMF
    contract facts.

    Args:
        umfs: the table set (UMF models) that was generated.
        output_dir: the directory ``SampleDataGenerator`` wrote into.
        dialect: adapter type dialect for ``column_types`` (``"duckdb"`` default).

    Returns:
        A :class:`SeedArtifacts` with ``seeds/<t>.csv`` files and ``column_types``.

    Raises:
        SeedEmitterError: a table's generated file is missing or has an unknown
            header column.
    """
    out_dir = Path(output_dir)
    files: dict[str, str] = {}
    column_types: dict[str, dict[str, str]] = {}

    for umf in umfs:
        umf_data = _umf_dict(umf)
        table = umf.table_name
        src = _resolve_generated_file(out_dir, table)
        column_names, rows = _read_generated_rows(src, umf_data)
        files[f"seeds/{table}.csv"] = _normalize_csv(column_names, rows)
        column_types[table] = seed_column_types(umf, dialect=dialect)

    return SeedArtifacts(files=files, column_types=column_types)


def render_seeds_config(
    column_types: dict[str, dict[str, str]],
    *,
    project_name: str = "tablespec_gold",
) -> str:
    """Render the ``seeds:`` block for ``dbt_project.yml``.

    Produces a per-seed ``+column_types`` mapping under
    ``seeds: <project_name>: <table>:`` so ``dbt seed`` loads each
    ``seeds/<table>.csv`` with the declared adapter types. Quoting the SQL type
    keeps parametrized types (``DECIMAL(18,2)``) valid YAML.

    The block is rendered separately (not folded into the project generators) so
    the caller can append it to a project's ``dbt_project.yml`` without coupling
    seeding into ``generate_dbt_project`` / ``generate_dbt_dag_project``.
    """
    lines = ["seeds:", f"  {project_name}:"]
    for table in sorted(column_types):
        lines.append(f"    {table}:")
        lines.append("      +column_types:")
        for column, sql_type in column_types[table].items():
            lines.append(f'        {column}: "{sql_type}"')
    return "\n".join(lines) + "\n"


__all__ = [
    "SeedArtifacts",
    "SeedEmitterError",
    "emit_seeds",
    "render_seeds_config",
    "seed_column_types",
]
