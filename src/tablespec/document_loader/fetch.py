"""Serial HTTPS acquisition with immutable objects and atomic local publication."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import fcntl
import stat
import os
from pathlib import Path
import re
import shutil
import queue
import socket
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .core import (
    LoaderError,
    contained,
    digest,
    encode,
    load_publication,
    parse_inventory,
    read_bounded,
    read_pack,
    MAX_STATE_BYTES,
    CANONICAL,
)


class DownloadError(LoaderError):
    def __init__(self, code: str, transient: bool = False, delay: float = 0):
        super().__init__(code)
        self.transient, self.delay, self.attempts = transient, delay, 0


@contextmanager
def https_response(url: str, media: str, user_agent: str, timeout: float):
    """HTTP client never follows redirects and never parses a document."""
    target = urlsplit(url)
    deadline = time.monotonic() + timeout
    connection = http.client.HTTPSConnection(target.hostname, port=443, timeout=timeout)

    def connect(address, timeout=None, source_address=None):
        results = queue.Queue(maxsize=1)

        def resolve():
            try:
                results.put(socket.getaddrinfo(*address, type=socket.SOCK_STREAM))
            except OSError as error:
                results.put(error)

        threading.Thread(target=resolve, daemon=True).start()
        try:
            addresses = results.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError() from None
        if isinstance(addresses, Exception):
            raise addresses
        failure = OSError()
        for family, kind, protocol, _, destination in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            stream = socket.socket(family, kind, protocol)
            try:
                stream.settimeout(remaining)
                if source_address:
                    stream.bind(source_address)
                stream.connect(destination)
                stream.settimeout(max(0.001, deadline - time.monotonic()))
                return stream
            except OSError as error:
                stream.close()
                failure = error
        raise failure

    connection._create_connection = connect

    def expire():
        stream = connection.sock
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            stream.close()

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        connection.request(
            "GET",
            target.path + ("?" + target.query if target.query else ""),
            headers={
                "User-Agent": user_agent,
                "Accept": media,
                "Accept-Encoding": "identity",
            },
        )
        client_socket = connection.sock
        response = connection.getresponse()
        response.set_deadline_timeout = client_socket.settimeout
        yield response
    finally:
        timer.cancel()
        connection.close()


class Transport:
    def __init__(
        self,
        inventory: dict,
        user_agent: str,
        opener=https_response,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.inventory, self.user_agent, self.opener = inventory, user_agent, opener
        self.sleep, self.clock = sleep, clock
        self.total, self.last_start = 0, None

    def download(self, entry: dict) -> tuple[bytes, int]:
        inv = self.inventory
        for attempt in range(inv["retries"] + 1):
            if self.total >= inv["max_total_bytes"]:
                error = DownloadError("BYTE_LIMIT")
                error.attempts = 0
                raise error
            if self.last_start is not None:
                self.sleep(
                    max(
                        0,
                        inv["request_interval_ms"] / 1000
                        - (self.clock() - self.last_start),
                    )
                )
            self.last_start = self.clock()
            deadline = self.last_start + inv["timeout_ms"] / 1000
            try:
                with self.opener(
                    entry["url"],
                    entry["media_type"],
                    self.user_agent,
                    inv["timeout_ms"] / 1000,
                ) as response:
                    chunks, count = [], 0
                    while True:
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            raise DownloadError("TIMEOUT", True)
                        response.set_deadline_timeout(remaining)
                        chunk = response.read1(
                            min(
                                65536,
                                inv["max_bytes"] - count + 1,
                                inv["max_total_bytes"] - self.total + 1,
                            )
                        )
                        count += len(chunk)
                        self.total += len(chunk)
                        if (
                            count > inv["max_bytes"]
                            or self.total > inv["max_total_bytes"]
                        ):
                            raise DownloadError("BYTE_LIMIT")
                        if self.clock() > deadline:
                            raise DownloadError("TIMEOUT", True)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    declared = response.headers.get("Content-Length")
                    if declared is not None and (
                        not re.fullmatch(r"[0-9]+", declared) or int(declared) != count
                    ):
                        raise DownloadError("INCOMPLETE_BODY", True)
                    if getattr(response, "length", 0) not in (None, 0):
                        raise DownloadError("INCOMPLETE_BODY", True)
                    if 300 <= response.status < 400:
                        raise DownloadError("REDIRECT")
                    if not 200 <= response.status < 300:
                        value = response.headers.get("Retry-After", "")
                        try:
                            delay = (
                                float(value)
                                if re.fullmatch(r"\d+(?:\.\d+)?", value)
                                else parsedate_to_datetime(value).timestamp()
                                - time.time()
                            )
                        except (ValueError, TypeError, OverflowError):
                            delay = 0
                        raise DownloadError(
                            "HTTP_" + str(response.status),
                            response.status == 429 or response.status >= 500,
                            min(60, max(0, delay)),
                        )
                    if (
                        response.headers.get("Content-Type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                        != entry["media_type"]
                    ):
                        raise DownloadError("MEDIA_TYPE")
                    if (
                        response.headers.get("Content-Encoding", "identity").lower()
                        != "identity"
                    ):
                        raise DownloadError("CONTENT_ENCODING")
                    raw = b"".join(chunks)
                    if entry["media_type"] == "application/pdf" and not raw.startswith(
                        b"%PDF-"
                    ):
                        raise DownloadError("PDF_MAGIC")
                    return raw, attempt + 1
            except (OSError, http.client.HTTPException, DownloadError) as exc:
                failure = (
                    exc
                    if isinstance(exc, DownloadError)
                    else DownloadError(
                        "TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSPORT",
                        True,
                    )
                )
                failure.attempts = attempt + 1
                if (
                    not failure.transient
                    or attempt >= inv["retries"]
                    or self.total >= inv["max_total_bytes"]
                ):
                    raise failure from exc
                self.sleep(min(60, max(failure.delay, 2**attempt)))
        raise AssertionError("unreachable")


def now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def atomic_write(root: Path, name: str, raw: bytes) -> None:
    temp = root / ("." + str(uuid4()) + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, root / name)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def immutable_write(path: Path, raw: bytes) -> bool:
    """Content-addressed originals are never overwritten, including unchanged refresh."""
    if path.exists():
        existing = read_bounded(path, len(raw))
        if existing != raw:
            raise LoaderError("OBJECT_HASH")
        return False
    temp = path.parent / ("." + str(uuid4()) + ".tmp")
    guard = path.parent / ("." + path.name + ".lock")
    fd = os.open(guard, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    lock = os.fdopen(fd, "r+b")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise LoaderError("OBJECT_LOCK_TYPE")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, LoaderError):
        lock.close()
        raise LoaderError("OBJECT_LOCKED_OR_UNSUPPORTED") from None
    try:
        if path.exists():
            if read_bounded(path, len(raw)) != raw:
                raise LoaderError("OBJECT_HASH")
            return False
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temp, path)
        return True
    finally:
        lock.close()
        temp.unlink(missing_ok=True)
        # Keep the inode stable; kernel releases the lock even after process death.


def fetch_sources(
    pack_path: Path,
    inventory_path: Path | None,
    state: Path,
    *,
    mode="backfill",
    rights="redistribute",
    user_agent: str | None = None,
    release_path: Path | None = None,
    opener=https_response,
    sleep=time.sleep,
    before_commit=None,
) -> dict:
    if mode not in ("backfill", "refresh", "replay"):
        raise LoaderError("RUN_CONFIGURATION")
    pack, pack_hash = read_pack(pack_path, release_path)
    pack_raw = read_bounded(pack_path, 4 * 1024 * 1024)
    if digest(pack_raw) != pack_hash:
        raise LoaderError("PACK_CHANGED")
    artifacts = {
        a["reference"]: contained(CANONICAL, a["reference"], 2 * 1024 * 1024)
        for a in pack["loader"]["artifacts"]
    }
    profile = pack["loader"]["profile"]
    inventory_raw = (
        read_bounded(inventory_path, 4 * 1024 * 1024) if inventory_path else None
    )
    inventory = (
        parse_inventory(inventory_raw, profile, rights)
        if inventory_raw is not None
        else None
    )
    if mode != "replay" and inventory is None:
        raise LoaderError("INVENTORY_REQUIRED")
    agent = user_agent or os.environ.get("UMF_LOADER_USER_AGENT", "")
    if (
        mode != "replay"
        and profile == "sec-filings"
        and not re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", agent, re.I)
    ):
        raise LoaderError("SEC_USER_AGENT")
    if "\r" in agent or "\n" in agent:
        raise LoaderError("USER_AGENT")
    state.mkdir(parents=True, exist_ok=True)
    try:
        lock = (state / "lock").open("xb")
    except FileExistsError:
        raise LoaderError("STATE_LOCKED") from None
    run_id = str(uuid4())
    receipt = dict(
        operation="umf.document-loader",
        version="1.0.0",
        run_id=run_id,
        pack_hash=pack_hash,
        inventory_hash="",
        mode=mode,
        rights=rights,
        started_at=now(),
        finished_at=now(),
        scope=[],
        status="failed",
        items=[],
    )
    committed = False
    try:
        lock.write(encode(dict(pid=os.getpid(), run_id=run_id)))
        lock.flush()
        pack_dir = state / "pack"
        if pack_dir.exists():
            if read_pack(pack_dir / "domain-pack.json")[1] != pack_hash:
                raise LoaderError("STATE_IDENTITY")
        else:
            stage = state / (".pack-" + run_id)
            stage.mkdir()
            try:
                immutable_write(stage / "domain-pack.json", pack_raw)
                for name, raw in artifacts.items():
                    immutable_write(stage / name, raw)
                read_pack(stage / "domain-pack.json")
                os.rename(stage, pack_dir)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        prior = load_publication(state) if (state / "current.json").exists() else None
        if mode == "replay":
            if prior is None:
                raise LoaderError("NO_REPLAY_SNAPSHOT")
            committed_raw = contained(
                prior["directory"], "inventory.json", 4 * 1024 * 1024
            )
            if inventory_raw is not None and digest(inventory_raw) != digest(
                committed_raw
            ):
                raise LoaderError("REPLAY_INVENTORY_MISMATCH")
            inventory_raw = committed_raw
            inventory = parse_inventory(inventory_raw, profile, rights)
        binding = dict(
            pack_hash=pack_hash,
            pack_id=pack["id"],
            pack_version=pack["version"],
            profile=profile,
            rights=rights,
            inventory_id=inventory["id"],
            implementation_version="1.0.0",
        )
        if prior and prior["manifest"]["binding"] != binding:
            raise LoaderError("STATE_IDENTITY")
        receipt["inventory_hash"] = digest(inventory_raw)
        receipt["scope"] = [e["id"] for e in inventory["entries"]]
        history = list(prior["manifest"]["history"]) if prior else []
        observations = list(prior["manifest"]["observations"]) if prior else []
        inventory_history = (
            dict(prior["manifest"]["inventory_history"]) if prior else {}
        )
        inventory_history[receipt["inventory_hash"]] = inventory_raw.decode()
        keys = {encode(r) for r in history}
        objects = state / "objects"
        objects.mkdir(exist_ok=True)
        if mode == "replay":
            rows = prior["manifest"]["rows"]
            receipt["items"] = [
                dict(id=r["id"], status="complete", sha256=r["sha256"], attempts=0)
                for r in rows
            ]
        else:
            rows = []
            transport = Transport(
                inventory,
                agent or "TableSpec Python document-loader/1.0.0",
                opener,
                sleep,
            )
            for entry in inventory["entries"]:
                try:
                    raw, attempts = transport.download(entry)
                    sha = digest(raw)
                    if entry.get("expected_sha256") and entry["expected_sha256"] != sha:
                        error = DownloadError("SOURCE_HASH")
                        error.attempts = attempts
                        raise error
                    row = dict(
                        id=entry["id"],
                        url=entry["url"],
                        sha256=sha,
                        media_type=entry["media_type"],
                        bytes=len(raw),
                        revision=sha,
                        metadata=entry.get("metadata", {}),
                        license=entry["license"],
                    )
                    added = immutable_write(objects / sha, raw)
                    rows.append(row)
                    if encode(row) not in keys:
                        history.append(row)
                        keys.add(encode(row))
                    observations.append(
                        dict(
                            run_id=run_id,
                            id=entry["id"],
                            sha256=sha,
                            url=entry["url"],
                            inventory_hash=receipt["inventory_hash"],
                            retrieved_at=now(),
                            media_type=row["media_type"],
                            metadata=row["metadata"],
                            license=row["license"],
                        )
                    )
                    receipt["items"].append(
                        dict(
                            id=entry["id"],
                            status="complete",
                            sha256=sha,
                            attempts=attempts,
                            new_revision=added,
                        )
                    )
                except (LoaderError, OSError) as exc:
                    receipt["items"].append(
                        dict(
                            id=entry["id"],
                            status="failed",
                            code=str(exc)
                            if isinstance(exc, LoaderError)
                            else "STATE_IO",
                            attempts=getattr(exc, "attempts", 1),
                        )
                    )
            if any(i["status"] == "failed" for i in receipt["items"]):
                raise LoaderError("INCOMPLETE_COVERAGE")
        sizes = {r["sha256"]: r["bytes"] for r in history}
        if (
            len(history) > 10000
            or len(observations) > 100000
            or len(inventory_history) > 10000
            or sum(sizes.values()) > MAX_STATE_BYTES
        ):
            raise LoaderError("STATE_LIMIT")
        receipt["status"] = "complete"
        receipt["finished_at"] = now()
        projection = b"".join(encode(r) for r in rows)
        manifest = dict(
            version="1.0.0",
            producer="tablespec-python/0.0.8",
            binding=binding,
            inventory_hash=receipt["inventory_hash"],
            receipt_hash=digest(encode(receipt)),
            projection_hash=digest(projection),
            projection_version="1.0.0",
            inventory_history=inventory_history,
            history=history,
            rows=rows,
            observations=observations,
        )
        raw_manifest = encode(manifest)
        if len(raw_manifest) > 100 * 1024 * 1024:
            raise LoaderError("STATE_LIMIT")
        directory = state / "publications" / run_id
        directory.mkdir(parents=True)
        for name, raw in (
            ("inventory.json", inventory_raw),
            ("documents.jsonl", projection),
            ("receipt.json", encode(receipt)),
            ("manifest.json", raw_manifest),
        ):
            immutable_write(directory / name, raw)
        if before_commit:
            before_commit()
        atomic_write(
            state,
            "current.json",
            encode(
                dict(
                    version="1.0.0",
                    manifest=f"publications/{run_id}/manifest.json",
                    sha256=digest(raw_manifest),
                )
            ),
        )
        committed = True
    except (LoaderError, OSError, ValueError) as exc:
        receipt["status"] = "failed"
        receipt["code"] = str(exc) if isinstance(exc, LoaderError) else "STATE_IO"
        receipt["finished_at"] = now()
    finally:
        try:
            (state / "runs").mkdir(exist_ok=True)
            atomic_write(state / "runs", run_id + ".json", encode(receipt))
        except OSError:
            if committed:
                receipt["cleanup_warning"] = True
            else:
                receipt["code"] = "RECEIPT_IO"
        try:
            lock.close()
            (state / "lock").unlink()
        except OSError:
            receipt["cleanup_warning"] = True
    return receipt
