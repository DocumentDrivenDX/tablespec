"""Portable document-loader admission and verified, bounded publication reading."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from umf.serialization import read_json_value

CANONICAL = Path(__file__).with_name("canonical")
MAX_STATE_BYTES = 500 * 1024 * 1024


class LoaderError(ValueError):
    """Closed diagnostic code; never includes source bodies or credentials."""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def read_bounded(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise LoaderError("FILE_LIMIT_OR_TYPE")
        chunks = []
        size = 0
        while chunk := os.read(fd, min(65536, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise LoaderError("FILE_LIMIT_OR_TYPE")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def contained(root: Path, reference: str, limit: int) -> bytes:
    if not isinstance(reference, str) or not reference or "\\" in reference:
        raise LoaderError("STATE_PATH")
    relative = Path(reference)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != reference
    ):
        raise LoaderError("STATE_PATH")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise LoaderError("STATE_PATH")
    return read_bounded(path, limit)


def canonical_release() -> dict:
    release = json.loads(read_bounded(CANONICAL / "release.json", 1024 * 1024))
    for item in release["artifacts"]:
        if (
            digest(contained(CANONICAL, item["reference"], 2 * 1024 * 1024))
            != item["sha256"]
        ):
            raise LoaderError("INSTALLED_RELEASE_HASH")
    return release


def verify_release(path: Path) -> dict:
    """Check an independently downloaded public release index; performs no network IO."""
    public = json.loads(read_bounded(path, 1024 * 1024))
    installed = canonical_release()
    for key in ("id", "version", "artifacts"):
        if public.get(key) != installed[key]:
            raise LoaderError("RELEASE_MISMATCH")
    return installed


def read_pack(path: Path, release_path: Path | None = None) -> tuple[dict, str]:
    raw = read_bounded(path, 4 * 1024 * 1024)
    pack = read_json_value(raw.decode(), "json")
    if not isinstance(pack, dict):
        raise LoaderError("PACK_STRUCTURE")
    if "preservation" in pack:
        from .preservation import PROFILE

        preservation = pack["preservation"]
        if not isinstance(preservation, dict) or any(
            preservation.get(k) != v for k, v in PROFILE.items()
        ):
            raise LoaderError("PRESERVATION_PROFILE")
    release = verify_release(release_path) if release_path else canonical_release()
    loader = pack.get("loader", {})
    schema = json.loads(read_bounded(CANONICAL / "loader.schema.json", 1024 * 1024))
    if not Draft202012Validator(schema).is_valid(loader):
        raise LoaderError("LOADER_STRUCTURE")
    if not isinstance(pack.get("id"), str) or not isinstance(pack.get("version"), str):
        raise LoaderError("PACK_IDENTITY")
    if (
        loader["id"] != release["id"]
        or loader["implementation_version"] != release["version"]
        or loader["artifacts"] != release["artifacts"]
    ):
        raise LoaderError("COMPANION_TRUST")
    for item in release["artifacts"]:
        if (
            digest(contained(path.parent, item["reference"], 2 * 1024 * 1024))
            != item["sha256"]
        ):
            raise LoaderError("COMPANION_HASH")
    return pack, digest(raw)


def valid_host(host: str) -> bool:
    return bool(
        host == host.lower()
        and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
        and "." in host
        and not re.fullmatch(r"[0-9.]+", host)
        and not host.endswith((".localhost", ".local", ".internal"))
        and ".." not in host
    )


def validate_url(value: str, hosts: list[str]) -> None:
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.fragment
            or url.port not in (None, 443)
            or not url.hostname
            or not valid_host(url.hostname)
            or url.hostname not in hosts
        ):
            raise LoaderError("SOURCE_URL_POLICY")
        # WHATWG URL rejects controls; don't let Python silently remove them.
        if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
            raise LoaderError("SOURCE_URL_POLICY")
    except ValueError as exc:
        raise LoaderError("SOURCE_URL_POLICY") from exc


def parse_inventory(raw: bytes, profile: str, rights: str) -> dict:
    if profile not in ("documents", "court-documents", "sec-filings") or rights not in (
        "local-use",
        "redistribute",
    ):
        raise LoaderError("RUN_CONFIGURATION")
    inventory = read_json_value(raw.decode(), "json")
    schema = json.loads(read_bounded(CANONICAL / "inventory.schema.json", 1024 * 1024))
    if not Draft202012Validator(schema).is_valid(inventory):
        raise LoaderError("INVENTORY_STRUCTURE")
    if len(inventory["entries"]) > inventory["max_documents"] or len(
        {e["id"] for e in inventory["entries"]}
    ) != len(inventory["entries"]):
        raise LoaderError("INVENTORY_IDENTITIES_OR_LIMIT")
    if any(not valid_host(h) for h in inventory["allowed_hosts"]):
        raise LoaderError("INVALID_HOST")
    if profile == "sec-filings" and (
        inventory["request_interval_ms"] < 1000
        or any(
            h not in ("www.sec.gov", "data.sec.gov") for h in inventory["allowed_hosts"]
        )
    ):
        raise LoaderError("SEC_POLICY")
    for entry in inventory["entries"]:
        validate_url(entry["url"], inventory["allowed_hosts"])
        if profile == "court-documents" and entry["media_type"] != "application/pdf":
            raise LoaderError("COURT_MEDIA")
        permission = entry["license"]["redistribution"]
        if permission == "restricted" or (
            rights == "redistribute" and permission != "allowed"
        ):
            raise LoaderError("SOURCE_RIGHTS")
    return inventory


def load_publication(root: Path) -> dict:
    """Verify the entire committed handoff, including retained history, before sink IO."""
    pointer = json.loads(read_bounded(root / "current.json", 1024 * 1024))
    reference = pointer.get("manifest", "")
    if pointer.get("version") != "1.0.0" or not re.fullmatch(
        r"publications/[a-f0-9-]{36}/manifest.json", reference
    ):
        raise LoaderError("STATE_POINTER")
    raw = contained(root, reference, 100 * 1024 * 1024)
    if digest(raw) != pointer.get("sha256"):
        raise LoaderError("MANIFEST_HASH")
    manifest = read_json_value(raw.decode(), "json")
    if (
        manifest.get("version") != "1.0.0"
        or manifest.get("projection_version") != "1.0.0"
    ):
        raise LoaderError("STATE_VERSION")
    directory = root / Path(reference).parent
    inventory_raw = contained(directory, "inventory.json", 4 * 1024 * 1024)
    if digest(inventory_raw) != manifest.get("inventory_hash"):
        raise LoaderError("INVENTORY_HASH")
    binding = manifest["binding"]
    inventory = parse_inventory(inventory_raw, binding["profile"], binding["rights"])
    if digest(contained(directory, "receipt.json", 10 * 1024 * 1024)) != manifest.get(
        "receipt_hash"
    ):
        raise LoaderError("RECEIPT_HASH")
    receipt = read_json_value(
        contained(directory, "receipt.json", 10 * 1024 * 1024).decode(), "json"
    )
    if (
        receipt.get("status") != "complete"
        or receipt.get("inventory_hash") != manifest["inventory_hash"]
        or receipt.get("pack_hash") != binding["pack_hash"]
    ):
        raise LoaderError("RECEIPT_CONTEXT")
    rows = manifest["rows"]
    projection = contained(directory, "documents.jsonl", 100 * 1024 * 1024)
    if digest(projection) != manifest.get("projection_hash") or projection != b"".join(
        encode(r) for r in rows
    ):
        raise LoaderError("PROJECTION_HASH")
    history = manifest["history"]
    if (
        len(history) > 10000
        or len(manifest["observations"]) > 100000
        or len(manifest["inventory_history"]) > 10000
    ):
        raise LoaderError("STATE_LIMIT")
    sizes = {}
    history_keys = {encode(r) for r in history}
    for row in history:
        if (
            not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
            or row["revision"] != row["sha256"]
            or type(row["bytes"]) is not int
            or not 0 <= row["bytes"] <= 50 * 1024 * 1024
        ):
            raise LoaderError("STATE_ROW")
        if row["sha256"] in sizes and sizes[row["sha256"]] != row["bytes"]:
            raise LoaderError("STATE_ROW")
        sizes[row["sha256"]] = row["bytes"]
    if sum(sizes.values()) > MAX_STATE_BYTES:
        raise LoaderError("STATE_LIMIT")
    for sha, size in sizes.items():
        raw_object = contained(root, "objects/" + sha, size)
        if len(raw_object) != size or digest(raw_object) != sha:
            raise LoaderError("OBJECT_HASH")
    for sha, text in manifest["inventory_history"].items():
        if digest(text.encode()) != sha:
            raise LoaderError("INVENTORY_HISTORY")
    if len(rows) != len(inventory["entries"]):
        raise LoaderError("INCOMPLETE_COVERAGE")
    for row, entry in zip(rows, inventory["entries"], strict=True):
        if (
            encode(row) not in history_keys
            or any(row[k] != entry[k] for k in ("id", "url", "media_type", "license"))
            or row["metadata"] != entry.get("metadata", {})
            or (
                entry.get("expected_sha256")
                and row["sha256"] != entry["expected_sha256"]
            )
        ):
            raise LoaderError("STATE_CONTEXT")
    for observation in manifest["observations"]:
        if (
            observation["sha256"] not in sizes
            or observation["inventory_hash"] not in manifest["inventory_history"]
        ):
            raise LoaderError("OBSERVATION_HISTORY")
    return {
        "manifest": manifest,
        "manifest_hash": pointer["sha256"],
        "directory": directory,
        "inventory": inventory,
    }
