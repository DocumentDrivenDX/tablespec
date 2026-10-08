"""Portable, deterministic CSV sample packs; generation remains disk backed."""

import csv
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from io import TextIOWrapper
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .sink import identifier
from .domains import get_run_domain_pack
from .streaming import GeneratedDataset


def read_csv_rows(path: Path, spec: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Read explicit local CSV rows with the pack's null and type conventions.

    A bounded consumer can use this for supplied external files as well as
    synthetic exports. No network retrieval or fabricated fallback occurs.
    """
    columns = [c for c in spec["columns"] if not c.get("internal")]
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != [c["name"] for c in columns]:
            raise ValueError("CSV header must exactly match the declared columns")
        for values in reader:
            if len(values) != len(columns):
                raise ValueError("CSV row width differs from the declared schema")
            row = {}
            for col, text in zip(columns, values, strict=True):
                value: Any = text
                dtype = col["data_type"].upper()
                try:
                    if text == "\\N":
                        value = None
                    elif dtype in ("INTEGER", "BIGINT", "SMALLINT", "INT"):
                        value = int(text)
                    elif dtype in ("DECIMAL", "FLOAT", "DOUBLE"):
                        number = Decimal(text)
                        if not number.is_finite():
                            raise ValueError("Non-finite CSV number")
                        value = number if dtype == "DECIMAL" else float(number)
                        if isinstance(value, float) and not math.isfinite(value):
                            raise ValueError("CSV number exceeds floating-point range")
                    elif dtype == "BOOLEAN":
                        if text.lower() not in ("true", "false"):
                            raise ValueError("Invalid CSV boolean")
                        value = text.lower() == "true"
                    elif dtype == "DATE":
                        value = date.fromisoformat(text)
                    elif dtype in ("DATETIME", "TIMESTAMP"):
                        value = datetime.fromisoformat(text)
                    elif dtype not in ("STRING", "TEXT", "VARCHAR", "CHAR"):
                        raise ValueError("Unsupported CSV type")
                except (ValueError, ArithmeticError):
                    raise ValueError(
                        "CSV value does not match its declared type"
                    ) from None
                row[col["name"]] = value
            yield row


def export_csv_zip(dataset: GeneratedDataset, output: Path) -> None:
    """Atomically publish verified rows, schemas and a report in a CSV ZIP.

    UTF-8 CSV uses RFC-style quoting and LF records, with an explicit \\N null
    marker. A string equal to that marker is rejected rather than losing its
    meaning. Empty strings remain empty strings. ZIP metadata has a fixed date
    and permissions so identical inputs produce identical archive bytes.
    """
    if not dataset.verified or set(dataset.report) != set(dataset.specs):
        raise ValueError("Dataset must pass verification before export")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:

            def entry(name: str) -> ZipInfo:
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                return info

            def metadata(name: str, value: Any) -> None:
                archive.writestr(
                    entry(name), json.dumps(value, sort_keys=True, indent=2)
                )

            metadata(
                "manifest.json",
                {
                    "format": "tablespec.csv-pack",
                    "version": 1,
                    "domain": dataset.config.domain,
                    "seed": dataset.config.random_seed,
                    "encoding": "UTF-8",
                    "null_value": "\\N",
                    "header": True,
                    "delimiter": ",",
                    "quote": '"',
                    "line_ending": "\n",
                    "tables": {
                        name: {"file": f"data/{name}.csv", "rows": dataset.counts[name]}
                        for name in sorted(dataset.specs)
                    },
                },
            )
            metadata("report.json", dataset.report)
            pack = get_run_domain_pack(dataset.config)
            if pack.metadata is not None:
                metadata("domain-pack.json", pack.metadata)
            for name in sorted(dataset.specs):
                identifier(name)  # Also prevents path traversal in ZIP members.
                spec = dataset.specs[name]
                metadata(f"schemas/{name}.json", spec)
                columns = [c["name"] for c in spec["columns"] if not c.get("internal")]
                with archive.open(
                    entry(f"data/{name}.csv"), "w", force_zip64=True
                ) as raw:
                    with TextIOWrapper(raw, encoding="utf-8", newline="") as stream:
                        # Quoted empty strings remain distinguishable from NULL
                        # in Spark's CSV reader; bare empty fields become null.
                        writer = csv.writer(
                            stream, lineterminator="\n", quoting=csv.QUOTE_ALL
                        )
                        writer.writerow(columns)
                        for batch in dataset.batches(name):
                            for row in batch:
                                values = [row[c] for c in columns]
                                if any(value == "\\N" for value in values):
                                    raise ValueError(
                                        "CSV value collides with the null marker"
                                    )
                                writer.writerow(
                                    [
                                        "\\N" if value is None else value
                                        for value in values
                                    ]
                                )
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
