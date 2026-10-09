"""Portable, deterministic CSV sample packs; generation remains disk backed."""

import csv
import hashlib
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
    if dataset.config.domain_pack_path is not None and dataset.schema_artifacts:
        from tablespec.umf_loader import UMFLoader
        from .domains import read_domain_pack

        source_pack = read_domain_pack(dataset.config.domain_pack_path)
        for schema in source_pack.get("schemas", []):
            if schema["format"] == "tablespec" and schema["id"] in dataset.specs:
                artifact = dataset.schema_artifacts[schema["reference"]]
                native = (
                    UMFLoader()
                    .load(artifact)
                    .model_dump(mode="json", exclude_none=True)
                )
                if native != dataset.specs.get(schema["id"]):
                    raise ValueError(
                        "Generation schema differs from admitted domain-pack schema"
                    )
    if dataset.source_metadata:
        sources = dataset.source_metadata.get("sources", {})
        included = {
            b["source_id"]
            for b in dataset.source_metadata.get("source_bindings", [])
            if b["role"] == "rows" and b["schema_id"] in dataset.specs
        }
        included.update(
            name
            for name, source in sources.items()
            if source.get("reference") in dataset.source_artifacts
        )
        for name in included:
            source = sources[name]
            if (
                source["kind"] == "external"
                and source.get("license", {}).get("redistribution") != "allowed"
            ):
                raise ValueError("Source redistribution is not cleared for ZIP export")
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

            def copy_admitted(path, target):
                digest = hashlib.sha256()
                total = 0
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > 10 * 1024 * 1024:
                            raise ValueError("Artifact exceeds byte budget")
                        digest.update(chunk)
                        target.write(chunk)
                if digest.hexdigest() != dataset.artifact_hashes.get(str(path)):
                    raise ValueError("Admitted artifact changed before publication")

            pack_metadata = dataset.source_metadata
            if pack_metadata is None:
                pack_metadata = get_run_domain_pack(dataset.config).metadata
            metadata(
                "manifest.json",
                {
                    "format": "tablespec.csv-pack",
                    "version": 1,
                    "domain": dataset.config.domain,
                    "seed": dataset.config.random_seed
                    if dataset.source_metadata is None
                    else (dataset.run_metadata or {}).get("seed"),
                    "run": dataset.run_metadata,
                    "origin": (dataset.run_metadata or {}).get("origin", "external")
                    if dataset.source_metadata is not None
                    else "synthetic",
                    "encoding": "UTF-8",
                    "null_value": "\\N",
                    "header": True,
                    "delimiter": ",",
                    "quote": '"',
                    "line_ending": "\n",
                    "schema_artifacts": {
                        schema["reference"]: f"schemas/{schema['id']}.json"
                        for schema in (pack_metadata or {}).get("schemas", [])
                        if schema["id"] in dataset.specs
                        or schema["reference"] in dataset.schema_artifacts
                    },
                    "source_artifacts": {
                        name: f"inputs/{name}"
                        for name in sorted(dataset.source_artifacts)
                    },
                    "tables": {
                        name: {"file": f"data/{name}.csv", "rows": dataset.counts[name]}
                        for name in sorted(dataset.specs)
                    },
                },
            )
            metadata("report.json", dataset.report)
            if pack_metadata is not None:
                metadata("domain-pack.json", pack_metadata)
            for name, path in sorted(dataset.source_artifacts.items()):
                with archive.open(entry(f"inputs/{name}"), "w") as target:
                    copy_admitted(path, target)
            for schema in (pack_metadata or {}).get("schemas", []):
                reference = schema["reference"]
                if reference in dataset.schema_artifacts:
                    identifier(schema["id"])
                    with archive.open(
                        entry(f"schemas/{schema['id']}.json"), "w"
                    ) as target:
                        copy_admitted(dataset.schema_artifacts[reference], target)
            for name in sorted(dataset.specs):
                identifier(name)  # Also prevents path traversal in ZIP members.
                spec = dataset.specs[name]
                declared = next(
                    (
                        s
                        for s in (pack_metadata or {}).get("schemas", [])
                        if s["id"] == name
                    ),
                    None,
                )
                if (
                    declared is None
                    or declared["reference"] not in dataset.schema_artifacts
                ):
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
