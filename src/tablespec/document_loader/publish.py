"""Offline publication ports and native Spark/Delta and DuckDB metadata sinks."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Protocol
from uuid import uuid4

from .core import (
    LoaderError,
    contained,
    digest,
    encode,
    load_publication,
    read_bounded,
    read_pack,
)
from .fetch import immutable_write

# This is the loader's source-metadata projection, never a domain financial/legal projection.
FIELDS = [
    (n, "BIGINT" if n == "bytes" else "STRING")
    for n in (
        "id",
        "url",
        "sha256",
        "revision",
        "media_type",
        "bytes",
        "metadata_json",
        "license_json",
        "pack_id",
        "pack_version",
        "loader_id",
        "loader_version",
        "profile",
        "inventory_hash",
        "publication_hash",
        "retrieved_at",
        "run_id",
        "object_path",
    )
]


def metadata_schema(pack: dict) -> dict:
    """Generate the common metadata projection for the admitted pack/loader profile."""
    return {
        "version": "1.0.0",
        "pack_id": pack["id"],
        "pack_version": pack["version"],
        "profile": pack["loader"]["profile"],
        "columns": [
            {"name": name, "data_type": kind, "nullable": False}
            for name, kind in FIELDS
        ],
        "key": ["pack_id", "pack_version", "id", "revision"],
    }


def target_parts(target: str, count: int) -> list[str]:
    parts = target.split(".")
    if (
        len(parts) != count
        or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p) for p in parts)
        or parts[0].lower() == "hive_metastore"
    ):
        raise LoaderError("TARGET_POLICY")
    return parts


class MetadataSink(Protocol):
    target: str

    def write(self, rows: list[dict], schema: dict, mode: str) -> None: ...
    def read(self, publication_hash: str) -> list[dict]: ...


class LocalObjects:
    """A caller-named local directory or mounted UC volume, keyed only by SHA-256."""

    def __init__(self, root: Path):
        self.root = root

    def path(self, sha: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise LoaderError("OBJECT_ID")
        return self.root / sha

    def write(self, sha: str, raw: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if digest(raw) != sha:
            raise LoaderError("OBJECT_HASH")
        immutable_write(self.path(sha), raw)

    def read(self, sha: str, size: int) -> bytes:
        return read_bounded(self.path(sha), size)


class SparkMetadataSink:
    """Use the existing SparkSQLSink adapter and the caller's session, including Connect."""

    def __init__(self, spark, target: str):
        from tablespec.sample_data.sink import SparkSQLSink

        self.parts = target_parts(target, 3)
        self.target, self.spark = target, spark
        self.sql = SparkSQLSink(spark)

    def write(self, rows: list[dict], schema: dict, mode: str) -> None:
        from pyspark.sql.types import StructType, StructField, StringType, LongType

        native_schema = StructType(
            [
                StructField(
                    c["name"],
                    LongType() if c["data_type"] == "BIGINT" else StringType(),
                    False,
                )
                for c in schema["columns"]
            ]
        )
        exists = self.spark.catalog.tableExists(self.target)
        if exists:
            actual = self.spark.table(self.target).schema
            if [(f.name, f.dataType.simpleString()) for f in actual] != [
                (f.name, f.dataType.simpleString()) for f in native_schema
            ]:
                raise LoaderError("TARGET_SCHEMA")
        frame = self.spark.createDataFrame(rows, schema=native_schema)
        if mode == "replace" or not exists:
            frame.write.format("delta").mode(
                "overwrite" if exists else "errorifexists"
            ).saveAsTable(self.target)
            return
        view = "document_loader_" + uuid4().hex
        frame.createOrReplaceTempView(view)
        quoted = ".".join("`" + p + "`" for p in self.parts)
        try:
            self.sql.execute(
                f"MERGE INTO {quoted} t USING `{view}` s ON t.pack_id=s.pack_id AND t.pack_version=s.pack_version AND t.id=s.id AND t.revision=s.revision WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *"
            )
        finally:
            self.spark.catalog.dropTempView(view)

    def read(self, publication_hash: str) -> list[dict]:
        from pyspark.sql.functions import col

        return [
            r.asDict(recursive=True)
            for r in self.spark.table(self.target)
            .where(col("publication_hash") == publication_hash)
            .limit(1001)
            .collect()
        ]


class DuckDBMetadataSink:
    """Optional native local sink; no Spark, Bun, network or dependency on source media."""

    def __init__(self, connection, target: str):
        self.parts = target_parts(target, 2)
        self.target, self.connection = target, connection
        self.quoted = ".".join('"' + p + '"' for p in self.parts)

    def preflight(self, schema: dict, mode: str) -> None:
        columns = schema["columns"]
        expected = [
            (c["name"], "BIGINT" if c["data_type"] == "BIGINT" else "VARCHAR")
            for c in columns
        ]
        existing = self.connection.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
            self.parts,
        ).fetchall()
        if existing and existing != [(name, kind, "NO") for name, kind in expected]:
            raise LoaderError("TARGET_SCHEMA")
        if existing:
            constraints = self.connection.execute(
                "SELECT constraint_type, constraint_column_names FROM duckdb_constraints() WHERE schema_name=? AND table_name=? AND constraint_type <> 'NOT NULL'",
                self.parts,
            ).fetchall()
            if constraints != [
                ("PRIMARY KEY", ["pack_id", "pack_version", "id", "revision"])
            ]:
                raise LoaderError("TARGET_CONSTRAINTS")

    def write(self, rows: list[dict], schema: dict, mode: str) -> None:
        self.preflight(schema, mode)
        columns = schema["columns"]
        expected = [
            (c["name"], "BIGINT" if c["data_type"] == "BIGINT" else "VARCHAR")
            for c in columns
        ]
        self.connection.execute("BEGIN TRANSACTION")
        try:
            ddl = ",".join(
                '"' + name + '" ' + kind + " NOT NULL" for name, kind in expected
            )
            self.connection.execute(
                f"CREATE TABLE IF NOT EXISTS {self.quoted} ({ddl}, PRIMARY KEY(pack_id,pack_version,id,revision))"
            )
            if mode == "replace":
                self.connection.execute(f"DELETE FROM {self.quoted}")
            names = [c["name"] for c in columns]
            insert = (
                f"INSERT OR REPLACE INTO {self.quoted} VALUES ("
                + ",".join("?" for _ in names)
                + ")"
            )
            if rows:
                self.connection.executemany(
                    insert, [[r[n] for n in names] for r in rows]
                )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def read(self, publication_hash: str) -> list[dict]:
        cursor = self.connection.execute(
            f"SELECT * FROM {self.quoted} WHERE publication_hash=? LIMIT 1001",
            [publication_hash],
        )
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]


def validate_volume(target: str, volume: str) -> Path:
    from tablespec.sample_data.sink import volume_path

    parts = target_parts(target, 3)
    path = volume_path(volume)
    if path.split("/")[2:4] != parts[:2]:
        raise LoaderError("TARGET_VOLUME_NAMESPACE")
    return Path(path)


def publish_sources(
    state: Path,
    sink: MetadataSink,
    objects: LocalObjects,
    *,
    mode="replace",
    pack_path: Path | None = None,
    release_path: Path | None = None,
) -> dict:
    """Offline: all preflight checks finish before the first object/table mutation."""
    if mode not in ("replace", "merge"):
        raise LoaderError("PUBLISH_MODE")
    publication = load_publication(state)
    pack, pack_hash = read_pack(
        pack_path or state / "pack/domain-pack.json", release_path
    )
    manifest = publication["manifest"]
    binding = manifest["binding"]
    if (
        pack_hash != binding["pack_hash"]
        or pack["id"] != binding["pack_id"]
        or pack["version"] != binding["pack_version"]
        or pack["loader"]["profile"] != binding["profile"]
    ):
        raise LoaderError("STATE_IDENTITY")
    schema = metadata_schema(pack)
    observations = {
        o["id"]: o
        for o in manifest["observations"]
        if o["inventory_hash"] == manifest["inventory_hash"]
    }
    if hasattr(sink, "preflight"):
        sink.preflight(schema, mode)
    rows, required = [], {}
    for source in manifest["rows"]:
        observation = observations.get(source["id"])
        if not observation or observation["sha256"] != source["sha256"]:
            raise LoaderError("OBSERVATION_HISTORY")
        row = {
            k: source[k]
            for k in ("id", "url", "sha256", "revision", "media_type", "bytes")
        }
        row.update(
            metadata_json=encode(source["metadata"]).decode().rstrip("\n"),
            license_json=encode(source["license"]).decode().rstrip("\n"),
            pack_id=pack["id"],
            pack_version=pack["version"],
            loader_id=pack["loader"]["id"],
            loader_version=pack["loader"]["implementation_version"],
            profile=binding["profile"],
            inventory_hash=manifest["inventory_hash"],
            publication_hash=publication["manifest_hash"],
            retrieved_at=observation["retrieved_at"],
            run_id=observation["run_id"],
            object_path=str(objects.path(source["sha256"])),
        )
        rows.append(row)
        required[source["sha256"]] = source["bytes"]
    # Freeze verified source bytes one bounded object at a time. Existing objects must agree.
    for sha, size in required.items():
        raw = contained(state, "objects/" + sha, size)
        if len(raw) != size or digest(raw) != sha:
            raise LoaderError("OBJECT_HASH")
        objects.write(sha, raw)
    sink.write(rows, schema, mode)
    stored = sink.read(publication["manifest_hash"])
    if len(stored) != len(rows) or {
        encode(dict(sorted(r.items()))) for r in stored
    } != {encode(dict(sorted(r.items()))) for r in rows}:
        raise LoaderError("ROW_READBACK")
    for sha, size in required.items():
        raw = objects.read(sha, size)
        if len(raw) != size or digest(raw) != sha:
            raise LoaderError("OBJECT_READBACK")
    receipt = dict(
        status="complete",
        operation="publish",
        target=sink.target,
        mode=mode,
        rows=len(rows),
        objects=len(required),
        publication_hash=publication["manifest_hash"],
        pack_id=pack["id"],
        pack_version=pack["version"],
        loader_version=pack["loader"]["implementation_version"],
        rights=binding["rights"],
        schema=schema,
    )
    return receipt
