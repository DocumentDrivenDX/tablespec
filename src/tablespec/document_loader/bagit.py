"""Bounded complete BagIt 1.0 SHA-256 handoffs (RFC 8493); no fetch.txt support."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
from uuid import uuid4
from urllib.parse import quote

from .preservation import preservation_metadata
from .core import LoaderError, contained, digest, encode, load_publication, read_pack

MAX_BAG_BYTES = 650 * 1024 * 1024


def manifest_bytes(values: dict[str, str]) -> bytes:
    return "".join(
        sha + "  " + name + "\n" for name, sha in sorted(values.items())
    ).encode()


def export_bag(state: Path, output: Path) -> dict:
    if output.exists():
        raise LoaderError("HANDOFF_OUTPUT_EXISTS")
    publication = load_publication(state)
    pack, pack_hash = read_pack(state / "pack/domain-pack.json")
    if pack_hash != publication["manifest"]["binding"]["pack_hash"]:
        raise LoaderError("STATE_IDENTITY")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / ("." + output.name + "." + uuid4().hex)
    stage.mkdir()
    values, total = {}, 0

    def write(reference: str, raw: bytes, expected: str | None = None) -> None:
        nonlocal total
        total += len(raw)
        if total > MAX_BAG_BYTES or (expected is not None and digest(raw) != expected):
            raise LoaderError("HANDOFF_HASH_OR_LIMIT")
        path = stage / "data" / reference
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        values["data/" + reference] = digest(raw)

    try:
        directory = publication["directory"]
        relative = directory.relative_to(state).as_posix()
        manifest = publication["manifest"]
        write(
            relative + "/manifest.json",
            contained(directory, "manifest.json", 100 * 1024 * 1024),
            publication["manifest_hash"],
        )
        write(
            "current.json",
            encode(
                {
                    "version": "1.0.0",
                    "manifest": relative + "/manifest.json",
                    "sha256": publication["manifest_hash"],
                }
            ),
        )
        for name, key, cap in [
            ("inventory.json", "inventory_hash", 4 * 1024 * 1024),
            ("receipt.json", "receipt_hash", 10 * 1024 * 1024),
            ("documents.jsonl", "projection_hash", 100 * 1024 * 1024),
        ]:
            write(relative + "/" + name, contained(directory, name, cap), manifest[key])
        for sha, size in {r["sha256"]: r["bytes"] for r in manifest["history"]}.items():
            write("objects/" + sha, contained(state, "objects/" + sha, size), sha)
        write(
            "pack/domain-pack.json",
            contained(state, "pack/domain-pack.json", 4 * 1024 * 1024),
            pack_hash,
        )
        for artifact in pack["loader"]["artifacts"]:
            write(
                "pack/" + artifact["reference"],
                contained(state / "pack", artifact["reference"], 2 * 1024 * 1024),
                artifact["sha256"],
            )
        premis, prov = preservation_metadata(state)
        tags = {
            "preservation.json": encode(premis),
            "provenance.jsonld": encode(prov),
            "bagit.txt": b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n",
            "bag-info.txt": (
                "Bagging-Date: "
                + datetime.now(timezone.utc).date().isoformat()
                + "\nPayload-Oxum: "
                + str(total)
                + "."
                + str(len(values))
                + "\nExternal-Identifier: "
                + quote(pack["id"], safe="")
                + "@"
                + quote(pack["version"], safe="")
                + "\n"
            ).encode(),
            "manifest-sha256.txt": manifest_bytes(values),
        }
        for name, raw in tags.items():
            (stage / name).write_bytes(raw)
        (stage / "tagmanifest-sha256.txt").write_bytes(
            manifest_bytes({name: digest(raw) for name, raw in tags.items()})
        )
        validate_bag(stage)
        os.rename(stage, output)
        return {
            "status": "complete",
            "format": "BagIt-1.0",
            "algorithm": "sha256",
            "payload_files": len(values),
            "payload_bytes": total,
            "publication_hash": publication["manifest_hash"],
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _manifest(root: Path, name: str, payload: bool) -> dict[str, str]:
    raw = contained(root, name, 4 * 1024 * 1024).decode()
    values = {}
    for line in raw.splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if (
            not match
            or match[2] in values
            or match[2].startswith("data/") != payload
            or match[2] == name
        ):
            raise LoaderError("BAG_MANIFEST")
        values[match[2]] = match[1]
    if len(values) > 10032:
        raise LoaderError("BAG_LIMIT")
    return values


def validate_bag(root: Path) -> Path:
    if (
        contained(root, "bagit.txt", 1024)
        != b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
    ):
        raise LoaderError("BAG_VERSION")
    values = _manifest(root, "manifest-sha256.txt", True)
    tags = _manifest(root, "tagmanifest-sha256.txt", False)
    if set(tags) != {
        "bagit.txt",
        "bag-info.txt",
        "manifest-sha256.txt",
        "preservation.json",
        "provenance.jsonld",
    }:
        raise LoaderError("BAG_TAGS")
    total = 0
    for name, sha in {**values, **tags}.items():
        cap = (
            100 * 1024 * 1024
            if name.endswith(("manifest.json", "documents.jsonl"))
            else 50 * 1024 * 1024
        )
        raw = contained(root, name, cap)
        if digest(raw) != sha:
            raise LoaderError("BAG_FIXITY")
        if name in values:
            total += len(raw)
            if total > MAX_BAG_BYTES:
                raise LoaderError("BAG_LIMIT")
    actual = set()
    for index, path in enumerate((root / "data").rglob("*")):
        if index > 20000:
            raise LoaderError("BAG_LIMIT")
        kind = path.lstat().st_mode
        if not (stat.S_ISREG(kind) or stat.S_ISDIR(kind)):
            raise LoaderError("BAG_FILE_TYPE")
        if path.is_symlink():
            raise LoaderError("BAG_SYMLINK")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(values):
        raise LoaderError("BAG_COMPLETENESS")
    if {p.name for p in root.iterdir()} != {
        "data",
        "bagit.txt",
        "bag-info.txt",
        "manifest-sha256.txt",
        "tagmanifest-sha256.txt",
        "preservation.json",
        "provenance.jsonld",
    }:
        raise LoaderError("BAG_TAGS")
    info = contained(root, "bag-info.txt", 65536).decode()
    fields = [line.split(": ", 1) for line in info.splitlines()]
    if any(len(item) != 2 for item in fields) or len(
        {item[0] for item in fields}
    ) != len(fields):
        raise LoaderError("BAG_INFO")
    if dict(fields).get("Payload-Oxum") != str(total) + "." + str(len(values)):
        raise LoaderError("BAG_OXUM")
    load_publication(root / "data")
    premis = json.loads(contained(root, "preservation.json", 50 * 1024 * 1024))
    checked_at = premis["events"][-1]["eventDateTime"]
    from datetime import datetime

    datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    expected, prov = preservation_metadata(root / "data", checked_at)
    if encode(expected) != contained(
        root, "preservation.json", 50 * 1024 * 1024
    ) or encode(prov) != contained(root, "provenance.jsonld", 50 * 1024 * 1024):
        raise LoaderError("BAG_PRESERVATION_MAPPING")
    return root / "data"
