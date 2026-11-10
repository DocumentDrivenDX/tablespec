# SPDX-License-Identifier: MIT OR Apache-2.0
"""``source: {kind: excel}`` and ``source: {kind: external}``."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from tablespec.ingestion import ExcelReader, ExternalTableReader, get_reader
from tablespec.ingestion.excel import (
    cell_text,
    detect_header_row,
    read_excel_records,
    umf_header_names,
)
from tablespec.lineage.providers import SourceLocationResolver
from tablespec.models.umf import UMF, ExcelSource, ExternalTableSource, UMFColumn

pytestmark = [
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

openpyxl = pytest.importorskip("openpyxl")


def _umf(source: dict) -> UMF:
    return UMF(
        version="1.0",
        table_name="invoices",
        columns=[
            UMFColumn(
                name="invoice_id", data_type="INTEGER", canonical_name="Invoice #"
            ),
            UMFColumn(name="amount", data_type="DECIMAL", precision=12, scale=2),
            UMFColumn(name="award_date", data_type="DATE", aliases=["Award Date"]),
        ],
        source=source,
    )


def _workbook(path, rows, sheet="Sheet1"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    wb.create_sheet("Other").append(["unrelated"])
    wb.save(path)
    return path


HEADER = ["Invoice #", "amount", "Award Date", None]
DATA = [
    [861855.0, 12.5, dt.datetime(2026, 3, 1), "x"],
    [None, None, None, None],
    [7, 1, None, None],
]


# --- model ---------------------------------------------------------------


@pytest.mark.no_spark
def test_excel_source_round_trips_on_umf():
    umf = _umf({"kind": "excel", "sheet": "Sheet1", "header_row": "auto"})
    assert isinstance(umf.effective_source(), ExcelSource)
    assert umf.effective_source().header_candidates == [0, 1]


@pytest.mark.no_spark
def test_excel_source_rejects_negative_header_row():
    with pytest.raises(ValidationError):
        ExcelSource(kind="excel", header_row=-1)


@pytest.mark.no_spark
def test_external_source_needs_a_table():
    with pytest.raises(ValidationError):
        ExternalTableSource(kind="external", table="")
    src = ExternalTableSource(kind="external", table="${catalog}.sales.claims")
    assert src.table.endswith("sales.claims")


# --- pure helpers --------------------------------------------------------


@pytest.mark.no_spark
def test_detect_header_row_prefers_best_match_and_later_ties():
    rows = [["Invoice Report Nov 2026"], HEADER, *DATA]
    known = ["Invoice #", "amount", "Award Date"]
    assert detect_header_row(rows, known, (0, 1)) == 1
    assert detect_header_row([["a"], ["b"]], known, (0, 1)) == 1  # tie -> later


@pytest.mark.no_spark
@pytest.mark.parametrize(
    ("value", "text"),
    [
        (861855.0, "861855"),
        (12.5, "12.5"),
        (True, "true"),
        (dt.datetime(2026, 3, 1), "2026-03-01"),
        (dt.datetime(2026, 3, 1, 9, 30), "2026-03-01 09:30:00"),
        (None, None),
    ],
)
def test_cell_text(value, text):
    assert cell_text(value) == text


@pytest.mark.no_spark
def test_umf_header_names_include_canonical_and_aliases():
    names = umf_header_names(_umf({"kind": "excel"}))
    assert {"Invoice #", "Award Date", "invoice_id", "amount"} <= set(names)


# --- reading -------------------------------------------------------------


@pytest.mark.no_spark
def test_read_records_fixed_header(tmp_path):
    path = _workbook(tmp_path / "w.xlsx", [HEADER, *DATA])
    headers, rows = read_excel_records(ExcelSource(kind="excel", path=str(path)))
    assert headers == ["Invoice #", "amount", "Award Date"]  # blank header dropped
    assert rows == [
        {"Invoice #": "861855", "amount": "12.5", "Award Date": "2026-03-01"},
        {"Invoice #": "7", "amount": "1", "Award Date": None},  # empty row skipped
    ]


@pytest.mark.no_spark
def test_read_records_auto_header_and_named_sheet(tmp_path):
    path = _workbook(tmp_path / "w.xlsx", [["Title row"], HEADER, *DATA], sheet="Data")
    spec = ExcelSource(kind="excel", path=str(path), sheet="data", header_row="auto")
    headers, rows = read_excel_records(spec, umf_header_names(_umf({"kind": "excel"})))
    assert headers[0] == "Invoice #"
    assert rows[0]["Invoice #"] == "861855"


@pytest.mark.no_spark
def test_auto_header_without_known_headers_raises(tmp_path):
    path = _workbook(tmp_path / "w.xlsx", [HEADER])
    with pytest.raises(ValueError, match="known headers"):
        read_excel_records(ExcelSource(kind="excel", path=str(path), header_row="auto"))


@pytest.mark.no_spark
def test_missing_sheet_and_duplicate_header_raise(tmp_path):
    path = _workbook(tmp_path / "w.xlsx", [["a", "a"]])
    with pytest.raises(ValueError, match="not found"):
        read_excel_records(ExcelSource(kind="excel", path=str(path), sheet="nope"))
    with pytest.raises(ValueError, match="duplicate header"):
        read_excel_records(ExcelSource(kind="excel", path=str(path)))


@pytest.mark.no_spark
def test_get_reader_dispatches_new_kinds():
    umf = _umf({"kind": "excel", "header_row": "auto"})
    reader = get_reader(umf.effective_source(), umf=umf)
    assert isinstance(reader, ExcelReader)
    assert "Invoice #" in (reader.known_headers or [])
    assert isinstance(
        get_reader(ExternalTableSource(kind="external", table="c.s.t")),
        ExternalTableReader,
    )


def test_excel_reader_lands_strings(spark_session, tmp_path):
    path = _workbook(tmp_path / "w.xlsx", [HEADER, *DATA])
    df = ExcelReader().read(ExcelSource(kind="excel", path=str(path)), spark_session)
    assert {f.dataType.simpleString() for f in df.schema.fields} == {"string"}
    assert df.count() == 2


def test_external_reader_reads_table_in_place(spark_session):
    spark_session.createDataFrame([(1,)], "id int").createOrReplaceTempView("ext_src")
    df = ExternalTableReader().read(
        ExternalTableSource(kind="external", table="ext_src"), spark_session
    )
    assert df.collect()[0]["id"] == 1


@pytest.mark.no_spark
def test_lineage_resolves_external_table():
    umf = _umf({"kind": "external", "table": "cat.sch.claims"})
    location = SourceLocationResolver().resolve("g", umf)
    assert location is not None
    assert location.path == "cat.sch.claims"
