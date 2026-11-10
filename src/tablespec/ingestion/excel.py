# SPDX-License-Identifier: MIT OR Apache-2.0
"""Excel worksheet reader (``source: {kind: excel}``).

Reads one worksheet with openpyxl (``umf-tablespec[excel]``) into an all-STRING
DataFrame, like the delimited reader (ADR-007): typing happens at ingest.
openpyxl is imported lazily so the package stays importable without it.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from tablespec.models.umf import ExcelSource

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from tablespec.models.umf import UMF, SourceSpec


def umf_header_names(umf: UMF) -> list[str]:
    """Every header a file may use for *umf*'s columns: names, canonical names, aliases."""
    names: list[str] = []
    for col in umf.columns:
        names.append(col.name)
        if col.canonical_name:
            names.append(col.canonical_name)
        names.extend(col.aliases or [])
    return names


def detect_header_row(
    rows: Sequence[Sequence[Any]],
    known_headers: Iterable[str],
    candidates: Sequence[int] = (0, 1),
) -> int:
    """The candidate row whose cells best match *known_headers*.

    Matching is on stripped, case-insensitive cell text. Ties go to the LATER
    candidate: newer workbook vintages commonly insert a title row above the
    header. Pure -- *rows* are the sheet's leading rows as cell values.
    """
    known = {str(k).strip().lower() for k in known_headers}
    best_row, best_score = candidates[-1], -1
    for row_index in reversed(candidates):
        cells = rows[row_index] if row_index < len(rows) else ()
        score = sum(
            1 for c in cells if c is not None and str(c).strip().lower() in known
        )
        if score > best_score:
            best_row, best_score = row_index, score
    return best_row


def cell_text(value: Any) -> str | None:
    """Stringify one cell as raw landing text.

    Whole-number floats drop the ``.0`` Excel's numeric storage adds (so
    ``861855.0`` lands as ``861855``); midnight datetimes land as ISO dates,
    other datetimes as ISO ``YYYY-MM-DD HH:MM:SS``; booleans as
    ``true``/``false``. ``None`` stays NULL.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, _dt.datetime):
        if value.time() == _dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    return str(value)


def _select_sheet(workbook: Any, sheet: str | int | None) -> Any:
    names = workbook.sheetnames
    if sheet is None:
        return workbook[names[0]]
    if isinstance(sheet, int):
        if not 0 <= sheet < len(names):
            msg = f"sheet index {sheet} out of range ({len(names)} sheet(s))"
            raise ValueError(msg)
        return workbook[names[sheet]]
    for name in names:
        if name.lower() == sheet.lower():
            return workbook[name]
    msg = f"sheet {sheet!r} not found; workbook has {names}"
    raise ValueError(msg)


def read_excel_records(
    spec: ExcelSource, known_headers: Iterable[str] | None = None
) -> tuple[list[str], list[dict[str, str | None]]]:
    """Read ``spec.path``'s worksheet as ``(headers, rows)`` of stringified cells.

    Columns with a blank header are dropped; a duplicated header is an error.
    Fully empty rows below the header are skipped.
    """
    from openpyxl import load_workbook

    if spec.path is None:
        msg = "ExcelSource.path must be set before reading"
        raise ValueError(msg)
    workbook = load_workbook(spec.path, read_only=True, data_only=True)
    try:
        rows = [
            list(r)
            for r in _select_sheet(workbook, spec.sheet).iter_rows(values_only=True)
        ]
    finally:
        workbook.close()

    if spec.header_row == "auto":
        if known_headers is None:
            msg = "ExcelSource header_row 'auto' needs known headers (pass the UMF)"
            raise ValueError(msg)
        header_index = detect_header_row(rows, known_headers, spec.header_candidates)
    else:
        header_index = spec.header_row
    if header_index >= len(rows):
        return [], []

    keep: list[tuple[int, str]] = []
    seen: set[str] = set()
    for i, cell in enumerate(rows[header_index]):
        header = cell_text(cell)
        if header is None or not header.strip():
            continue
        header = header.strip()
        if header in seen:
            msg = f"duplicate header {header!r} in sheet row {header_index}"
            raise ValueError(msg)
        seen.add(header)
        keep.append((i, header))

    records: list[dict[str, str | None]] = []
    for row in rows[header_index + 1 :]:
        values = {h: cell_text(row[i]) if i < len(row) else None for i, h in keep}
        if any(v is not None and v != "" for v in values.values()):
            records.append(values)
    return [h for _, h in keep], records


class ExcelReader:
    """Excel worksheet reader; every column lands as STRING.

    ``known_headers`` (see :func:`umf_header_names`) is needed only for
    ``header_row: auto``.
    """

    def __init__(self, known_headers: Iterable[str] | None = None) -> None:
        self.known_headers = list(known_headers) if known_headers is not None else None

    def read(self, spec: SourceSpec, spark: SparkSession) -> DataFrame:
        if not isinstance(spec, ExcelSource):
            msg = f"ExcelReader requires an excel source, got kind={spec.kind!r}"
            raise TypeError(msg)
        from tablespec.ingestion import create_string_dataframe

        headers, records = read_excel_records(spec, self.known_headers)
        return create_string_dataframe(spark, records, headers)


__all__ = [
    "ExcelReader",
    "cell_text",
    "detect_header_row",
    "read_excel_records",
    "umf_header_names",
]
