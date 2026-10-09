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


def validate_profile(metadata: dict[str, Any]) -> None:
    """Admission for the exact trusted execution subset of CONTRACT-053."""
    profile = metadata["execution_profile"]
    allowed = {
        "version",
        "targets",
        "mode",
        "scales",
        "identity_columns",
        "include_sources",
        "qualification",
    }
    if (
        not isinstance(profile, dict)
        or set(profile) - allowed
        or profile.get("version") != "1.0.0"
    ):
        raise ValueError("Unsupported execution profile")
    if profile.get("mode") not in {"fixed", "scenario-replay"} or not isinstance(
        profile.get("qualification"), str
    ):
        raise ValueError("Unsupported execution mode or qualification")
    schemas = {entry["id"]: entry for entry in metadata.get("schemas", [])}
    targets = profile.get("targets")
    if (
        not isinstance(targets, dict)
        or not targets
        or set(targets) - {"tabular", "graph"}
    ):
        raise ValueError("Unsupported schema target")
    for target, selected in targets.items():
        if (
            not isinstance(selected, list)
            or not selected
            or any(not isinstance(n, str) for n in selected)
            or len(selected) != len(set(selected))
        ):
            raise ValueError("Invalid target schema selection")
        for name in selected:
            if name not in schemas or schemas[name]["format"] != (
                "tablespec" if target == "tabular" else "umf"
            ):
                raise ValueError("Target schema format or identity mismatch")
    included = profile.get("include_sources")
    if (
        not isinstance(included, list)
        or any(not isinstance(n, str) for n in included)
        or len(included) != len(set(included))
        or any(name not in metadata.get("sources", {}) for name in included)
    ):
        raise ValueError("Unresolved source inclusion")
    if profile["mode"] == "scenario-replay":
        scales, identities = profile.get("scales"), profile.get("identity_columns")
        if (
            not isinstance(scales, dict)
            or not scales
            or any(type(n) is not int or not 1 <= n <= 10000 for n in scales.values())
        ):
            raise ValueError("Invalid scenario scale")
        selected = targets.get("tabular", [])
        if (
            not isinstance(identities, dict)
            or set(identities) != set(selected)
            or any(
                not isinstance(cols, list)
                or not cols
                or any(not isinstance(c, str) for c in cols)
                or len(cols) != len(set(cols))
                or any(not isinstance(c, str) or not c for c in cols)
                for cols in identities.values()
            )
        ):
            raise ValueError("Invalid identity column mapping")


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
        profile = metadata.get("execution_profile")
        if profile is not None:
            validate_profile(metadata)
        selected = profile["targets"]["tabular"] if profile else None
        specs = {}
        schema_artifacts = {}
        for schema in metadata.get("schemas", []):
            artifact = local_artifact(root, schema["reference"])
            if artifact.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Schema exceeds byte budget")
            schema_artifacts[schema["reference"]] = artifact
            if selected is not None and schema["id"] not in selected:
                continue
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
            if binding["role"] != "rows" or (
                selected is not None and binding["schema_id"] not in selected
            ):
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
        self.schema_artifacts = schema_artifacts
        self.artifact_hashes = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in schema_artifacts.values()
        }
        try:
            mandatory = {
                b["source_id"]
                for b in metadata.get("source_bindings", [])
                if b["role"] == "rows" and b["schema_id"] in specs
            }
            included = (
                set(profile["include_sources"]) | mandatory
                if profile
                else set(metadata["sources"])
            )
            total_bytes = sum(p.stat().st_size for p in schema_artifacts.values())
            for source_id in sorted(included):
                source = metadata["sources"][source_id]
                reference = source.get("reference", "")
                if ":" in reference or not reference:
                    continue
                artifact = checked_source(root, source)
                total_bytes += artifact.stat().st_size
                if (
                    artifact.stat().st_size > 10 * 1024 * 1024
                    or total_bytes > 100 * 1024 * 1024
                ):
                    raise ValueError("Included sources exceed byte budget")
                self.source_artifacts[reference] = artifact
                self.artifact_hashes[str(artifact)] = source["checksum"]["value"]
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
                if count + sum(self.counts.values()) > 100000:
                    raise ValueError("Template rows exceed budget")
            self.counts[name] = count
            self.report[name] = {
                "row_count": count,
                "fk_orphan_count": 0,
                "null_violations": 0,
                "uniqueness_violations": 0,
            }
        self.verify_foreign_keys()
        self.db.commit()
        self.verified = True

    def verify_foreign_keys(self) -> None:
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
