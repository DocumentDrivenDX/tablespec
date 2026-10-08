"""Explicit local CSV ingestion into the existing verified disk-backed spool."""

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from umf import read_json_value

from .archive import read_csv_rows
from .config import GenerationConfig
from .domains import read_domain_pack
from .sink import identifier
from .streaming import GeneratedDataset, _decimal_canonical


def local_artifact(root: Path, reference: str) -> Path:
    """Resolve local files only; reject traversal, remote URLs and escaping symlinks."""
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts or ":" in reference:
        raise ValueError("Source reference must stay inside the local pack")
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError("Source reference leaves the local pack")
    return resolved


def checked_source(root: Path, source: dict[str, Any]) -> Path:
    """Require explicit redistribution clearance and pinned bytes before inclusion."""
    if source["kind"] != "external":
        raise ValueError("CSV ingestion requires external sources")
    if source.get("license", {}).get("redistribution") != "allowed":
        raise ValueError("Source redistribution is not cleared")
    checksum = source.get("checksum", {})
    if checksum.get("algorithm") != "sha256":
        raise ValueError("Source requires a SHA-256 checksum")
    path = local_artifact(root, source["reference"])
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != checksum["value"]:
        raise ValueError("Source checksum differs from pinned metadata")
    return path


class ImportedDataset(GeneratedDataset):
    """Reuse generation's spool, constraints, batching, SQL sink and ZIP exporter.

    Only declared local CSV row sources are read. Reference attachments are
    included only when local, checksum pinned and explicitly cleared. Remote
    references remain metadata. No generator runs and no rows are fabricated.
    """

    def __init__(self, path: Path, pack_path: Path) -> None:
        metadata = read_domain_pack(pack_path)
        root = pack_path.resolve().parent
        specs = {}
        for schema in metadata.get("schemas", []):
            if schema["format"] != "tablespec":
                raise ValueError("CSV ingestion supports TableSpec schemas only")
            identifier(schema["id"])
            spec = read_json_value(
                local_artifact(root, schema["reference"]).read_text(encoding="utf-8")
            )
            from tablespec.models.umf import UMF

            if not isinstance(spec, dict):
                raise ValueError("Tabular schema must be an object")
            UMF.model_validate(spec)
            if spec["table_name"] != schema["id"]:
                raise ValueError("Schema identity must match its table name")
            specs[schema["id"]] = spec
        if not specs:
            raise ValueError("No tabular schemas declared")
        row_sources: dict[str, Path] = {}
        for binding in metadata.get("source_bindings", []):
            if binding["role"] != "rows":
                continue
            name = binding["schema_id"]
            source = metadata["sources"][binding["source_id"]]
            if name in row_sources or source.get("format") != "csv":
                raise ValueError("Each table requires exactly one local CSV row source")
            row_sources[name] = checked_source(root, source)
        if set(row_sources) != set(specs):
            raise ValueError("Every schema requires a CSV row source")
        # A zero-row initialization reuses the shared spool. The legacy healthcare
        # registry is constructed but never executes: generate() refuses below.
        super().__init__(path, specs, dict.fromkeys(specs, 0), GenerationConfig())
        self.config.domain = metadata["id"]
        self.source_metadata = metadata
        self.row_sources = row_sources
        try:
            for source in metadata["sources"].values():
                reference = source.get("reference", "")
                if ":" in reference or not reference:
                    continue
                artifact = checked_source(root, source)
                self.source_artifacts[reference] = artifact
            self._ingest()
        except BaseException:
            self.close()
            raise

    def batches(self, table: str, batch_size: int = 500):
        """Recover exact numeric carriers from the shared JSON spool."""
        decimal_columns = [
            c["name"]
            for c in self.specs[table]["columns"]
            if c["data_type"].upper() == "DECIMAL"
        ]
        for batch in super().batches(table, batch_size):
            for row in batch:
                for column in decimal_columns:
                    if row[column] is not None:
                        row[column] = Decimal(row[column])
            yield batch

    def generate(self) -> dict[str, Any]:
        """Refuse invented substitution for official or otherwise external rows."""
        raise ValueError("Imported sources cannot be synthetically generated")

    def _ingest(self) -> None:
        for name, spec in self.specs.items():
            columns = [c for c in spec["columns"] if not c.get("internal")]
            unique, rules = self._constraints(spec, columns)
            count = 0
            for index, row in enumerate(read_csv_rows(self.row_sources[name], spec)):
                # The shared spool represents dates as ISO text; SQL literals use
                # column types. Exact Decimal values stay text in JSON, never float.
                normalized = {
                    key: value.isoformat()
                    if isinstance(value, (date, datetime))
                    else _decimal_canonical(value)
                    if isinstance(value, Decimal)
                    else value
                    for key, value in row.items()
                }
                self._check(name, normalized, columns, unique, rules)
                self.db.execute(
                    "INSERT INTO rows VALUES (?,?,?)",
                    (name, index, json.dumps(normalized, default=str)),
                )
                count += 1
            self.counts[name] = count
            self.report[name] = {
                "row_count": count,
                "fk_orphan_count": 0,
                "null_violations": 0,
                "uniqueness_violations": 0,
            }
        # Check all parents after ingest, supporting cyclic/self-referential data.
        # json_extract compares typed values without loading parent key pools.
        for name, spec in self.specs.items():
            for fk in spec.get("relationships", {}).get("foreign_keys", []):
                parent = fk["references_table"]
                if fk.get("cross_pipeline") or parent not in self.specs:
                    raise ValueError("External foreign-key parent is unsupported")
                for column in (fk["column"], fk["references_column"]):
                    identifier(column)
                colpath, parentpath = (
                    "$." + fk["column"],
                    "$." + fk["references_column"],
                )
                orphans = self.db.execute(
                    "SELECT COUNT(*) FROM rows c WHERE c.tbl=? "
                    "AND json_extract(c.body,?) IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM rows p WHERE p.tbl=? "
                    "AND json_extract(p.body,?)=json_extract(c.body,?))",
                    (name, colpath, parent, parentpath, colpath),
                ).fetchone()[0]
                if orphans:
                    raise ValueError(f"CSV foreign-key orphan: {name}.{fk['column']}")
        self.db.commit()
        self.verified = True
