"""Document acquisition and offline sink evidence; never needs public-network access."""

from contextlib import contextmanager
from io import BytesIO
import json
import shutil

import duckdb
import pytest
from typer.testing import CliRunner

from tablespec.document_loader import (
    DuckDBMetadataSink,
    LoaderError,
    LocalObjects,
    export_bag,
    fetch_sources,
    load_publication,
    publish_sources,
    validate_bag,
    validate_volume,
    verify_release,
)
from tablespec.document_loader.cli import app
from tablespec.document_loader.core import CANONICAL, digest, encode, read_pack

BODY = b"%PDF-1.7\noriginal fixture bytes\n"


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "pack"
    shutil.copytree(CANONICAL, root)
    release = json.loads((root / "release.json").read_text())
    pack = {
        "id": "court-fixture",
        "version": "1.0.0",
        "loader": {
            "version": "1.0.0",
            "id": "umf.document-loader",
            "implementation_version": "1.0.0",
            "profile": "court-documents",
            "runtime": "bun",
            "entrypoint": "run.ts",
            "configuration_schema": "inventory.schema.json",
            "qualification": "Fixed original document fixtures",
            "artifacts": release["artifacts"],
        },
    }
    (root / "pack.json").write_bytes(encode(pack))
    inv = {
        "version": "1.0.0",
        "id": "selection",
        "allowed_hosts": ["court.example.org"],
        "request_interval_ms": 100,
        "max_bytes": 1024,
        "max_total_bytes": 4096,
        "max_documents": 10,
        "timeout_ms": 1000,
        "retries": 0,
        "entries": [
            {
                "id": "case:1",
                "url": "https://court.example.org/opinion.pdf",
                "media_type": "application/pdf",
                "license": {"redistribution": "unknown"},
                "metadata": {"future": {"meaning": "opaque"}},
            }
        ],
    }
    path = tmp_path / "inventory.json"
    path.write_bytes(encode(inv))
    return root / "pack.json", path, tmp_path / "state", inv


class Response:
    def __init__(self, raw=BODY, status=200, media="application/pdf", headers=None):
        self.stream, self.status = BytesIO(raw), status
        self.headers = {"Content-Type": media, **(headers or {})}

    def set_deadline_timeout(self, timeout):
        assert 0 < timeout <= 1

    def read1(self, n):
        return self.stream.read(n)


def transport(responses, calls=None):
    @contextmanager
    def opener(url, media, agent, timeout):
        if calls is not None:
            calls.append((url, agent))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        yield response

    return opener


def collect(corpus, responses=None, **kwargs):
    pack, inventory, state, inv = corpus
    kwargs.setdefault("rights", "local-use")
    inventory.write_bytes(encode(inv))
    return fetch_sources(
        pack,
        inventory,
        state,
        opener=transport(responses or [Response()]),
        sleep=lambda _: None,
        **kwargs,
    )


def test_original_refresh_replay_and_revisions(corpus):
    _, _, state, _ = corpus
    assert collect(corpus)["status"] == "complete"
    sha = digest(BODY)
    original = state / "objects" / sha
    before = original.stat()
    receipt = collect(corpus, mode="refresh")
    assert receipt["status"] == "complete" and not receipt["items"][0]["new_revision"]
    assert (
        original.stat().st_ino == before.st_ino
        and original.stat().st_mtime_ns == before.st_mtime_ns
    )
    assert len(load_publication(state)["manifest"]["history"]) == 1
    changed = BODY + b"changed"
    assert collect(corpus, [Response(changed)], mode="refresh")["status"] == "complete"
    assert len(load_publication(state)["manifest"]["history"]) == 2
    replay = fetch_sources(
        corpus[0],
        None,
        state,
        mode="replay",
        rights="local-use",
        opener=lambda *a: pytest.fail("replay contacted network"),
    )
    assert replay["status"] == "complete" and replay["items"][0]["attempts"] == 0
    assert (state / "objects" / digest(changed)).read_bytes() == changed


@pytest.mark.parametrize(
    "url",
    [
        "http://court.example.org/a.pdf",
        "https://other.example.org/a.pdf",
        "https://user:secret@court.example.org/a.pdf",
        "https://court.example.org:444/a.pdf",
        "https://court.example.org/a.pdf#frag",
        "https://court.example.org/a\npdf",
        "https://127.0.0.1/a.pdf",
    ],
)
def test_url_preflight(corpus, url):
    corpus[3]["entries"][0]["url"] = url
    with pytest.raises(LoaderError, match="SOURCE_URL_POLICY"):
        collect(corpus)
    assert not corpus[2].exists()


@pytest.mark.parametrize(
    "rights,permission", [("local-use", "restricted"), ("redistribute", "unknown")]
)
def test_rights(corpus, rights, permission):
    corpus[3]["entries"][0]["license"]["redistribution"] = permission
    with pytest.raises(LoaderError, match="SOURCE_RIGHTS"):
        collect(corpus, rights=rights)


@pytest.mark.parametrize(
    "response,code",
    [
        (
            Response(
                b"redirect",
                302,
                headers={"Location": "https://court.example.org/other"},
            ),
            "REDIRECT",
        ),
        (Response(BODY, media="text/plain"), "MEDIA_TYPE"),
        (Response(b"not pdf"), "PDF_MAGIC"),
        (Response(b"unavailable", 403), "HTTP_403"),
    ],
)
def test_failed_refresh_keeps_publication(corpus, response, code):
    assert collect(corpus)["status"] == "complete"
    prior = (corpus[2] / "current.json").read_bytes()
    receipt = collect(corpus, [response], mode="refresh")
    assert receipt["status"] == "failed" and receipt["items"][0]["code"] == code
    assert (corpus[2] / "current.json").read_bytes() == prior


def test_hash_pin(corpus):
    corpus[3]["entries"][0]["expected_sha256"] = digest(BODY)
    assert collect(corpus)["status"] == "complete"
    receipt = collect(corpus, [Response(BODY + b"different")], mode="refresh")
    assert receipt["items"][0]["code"] == "SOURCE_HASH"


def test_byte_caps_and_failed_attempt_budget(corpus):
    corpus[3]["max_bytes"] = 5
    assert collect(corpus)["items"][0]["code"] == "BYTE_LIMIT"
    corpus[3]["max_bytes"] = 1024
    corpus[3]["max_total_bytes"] = 5
    corpus[3]["retries"] = 2
    corpus[3]["entries"].append({**corpus[3]["entries"][0], "id": "case:2"})
    calls = []
    corpus[1].write_bytes(encode(corpus[3]))
    receipt = fetch_sources(
        corpus[0],
        corpus[1],
        corpus[2],
        opener=transport([Response(b"12345", 500)], calls),
        sleep=lambda _: None,
        rights="local-use",
    )
    assert len(calls) == 1
    assert (
        receipt["items"][1]["code"] == "BYTE_LIMIT"
        and receipt["items"][1]["attempts"] == 0
    )


def test_retries_timeout_and_interval(corpus):
    corpus[3]["retries"] = 1
    sleeps = []
    corpus[1].write_bytes(encode(corpus[3]))
    receipt = fetch_sources(
        corpus[0],
        corpus[1],
        corpus[2],
        opener=transport(
            [Response(b"retry", 429, headers={"Retry-After": "0"}), Response()]
        ),
        sleep=sleeps.append,
        rights="local-use",
    )
    assert receipt["status"] == "complete" and receipt["items"][0]["attempts"] == 2
    assert any(delay >= 1 for delay in sleeps)
    receipt = collect(corpus, [TimeoutError(), TimeoutError()], mode="refresh")
    assert (
        receipt["items"][0]["code"] == "TIMEOUT"
        and receipt["items"][0]["attempts"] == 2
    )


def test_sec_policy_agent_and_exact_json(corpus, monkeypatch):
    pack = json.loads(corpus[0].read_text())
    pack["loader"]["profile"] = "sec-filings"
    corpus[0].write_bytes(encode(pack))
    inv = corpus[3]
    inv["allowed_hosts"] = ["data.sec.gov"]
    inv["request_interval_ms"] = 1000
    inv["entries"][0].update(
        url="https://data.sec.gov/fixture.json", media_type="application/json"
    )
    monkeypatch.delenv("UMF_LOADER_USER_AGENT", raising=False)
    with pytest.raises(LoaderError, match="SEC_USER_AGENT"):
        collect(corpus)
    raw = b'{"amount":9007199254740993.0100}'
    receipt = collect(
        corpus,
        [Response(raw, media="application/json")],
        user_agent="Fixture contact@example.org",
    )
    assert receipt["status"] == "complete"
    assert (corpus[2] / "objects" / digest(raw)).read_bytes() == raw
    inv["request_interval_ms"] = 999
    with pytest.raises(LoaderError, match="SEC_POLICY"):
        collect(corpus, user_agent="Fixture contact@example.org")


def test_state_lock_and_precommit_failure(corpus):
    assert collect(corpus)["status"] == "complete"
    prior = (corpus[2] / "current.json").read_bytes()

    def stop():
        raise LoaderError("BEFORE_COMMIT")

    assert (
        collect(corpus, [Response(BODY + b"new")], mode="refresh", before_commit=stop)[
            "status"
        ]
        == "failed"
    )
    assert (corpus[2] / "current.json").read_bytes() == prior
    (corpus[2] / "lock").write_bytes(b"occupied")
    with pytest.raises(LoaderError, match="STATE_LOCKED"):
        collect(corpus)


def test_canonical_trust(corpus, tmp_path):
    assert read_pack(corpus[0])[0]["loader"]["runtime"] == "bun"
    release = tmp_path / "public-release.json"
    release.write_bytes((CANONICAL / "release.json").read_bytes())
    assert verify_release(release)["version"] == "1.0.0"
    pack = json.loads(corpus[0].read_text())
    pack["loader"]["artifacts"][0]["sha256"] = "0" * 64
    corpus[0].write_bytes(encode(pack))
    with pytest.raises(LoaderError, match="COMPANION_TRUST"):
        read_pack(corpus[0])


def test_bagit_offline_duckdb_and_orphans(corpus, tmp_path, monkeypatch):
    assert collect(corpus)["status"] == "complete"
    bag = tmp_path / "handoff"
    report = export_bag(corpus[2], bag)
    assert report["format"] == "BagIt-1.0"
    state = validate_bag(bag)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(
        "http.client.HTTPSConnection",
        lambda *a, **k: pytest.fail("publish contacted public network"),
    )
    with duckdb.connect() as connection:
        sink = DuckDBMetadataSink(connection, "main.documents")
        objects = LocalObjects(tmp_path / "published-objects")
        result = publish_sources(state, sink, objects)
        assert result["rows"] == 1 and objects.read(digest(BODY), len(BODY)) == BODY
        assert connection.execute(
            "SELECT pack_version,loader_version,metadata_json FROM main.documents"
        ).fetchone() == ("1.0.0", "1.0.0", '{"future":{"meaning":"opaque"}}')
        assert publish_sources(state, sink, objects, mode="merge")["rows"] == 1
        assert (
            connection.execute("SELECT count(*) FROM main.documents").fetchone()[0] == 1
        )
    (bag / "data/objects" / digest(BODY)).write_bytes(b"tampered")
    with pytest.raises(LoaderError, match="BAG_FIXITY"):
        validate_bag(bag)


def test_readback_refuses_wrong_rows_or_objects(corpus, tmp_path):
    collect(corpus)

    class MissingRows:
        target = "main.documents"

        def write(self, rows, schema, mode):
            pass

        def read(self, publication_hash):
            return []

    with pytest.raises(LoaderError, match="ROW_READBACK"):
        publish_sources(corpus[2], MissingRows(), LocalObjects(tmp_path / "objects"))
    with duckdb.connect() as connection:

        class CorruptObjects(LocalObjects):
            def read(self, sha, size):
                return b"corrupt"

        with pytest.raises(LoaderError, match="OBJECT_READBACK"):
            publish_sources(
                corpus[2],
                DuckDBMetadataSink(connection, "main.documents"),
                CorruptObjects(tmp_path / "other-objects"),
            )


def test_target_volume_and_schema_refusal(corpus, tmp_path):
    assert (
        str(
            validate_volume(
                "catalog.schema.docs", "/Volumes/catalog/schema/originals/collection"
            )
        )
        == "/Volumes/catalog/schema/originals/collection"
    )
    for volume in [
        "/Volumes/other/schema/volume",
        "/Volumes/catalog/other/volume",
        "/Volumes/catalog/schema/volume/../other",
    ]:
        with pytest.raises(ValueError):
            validate_volume("catalog.schema.docs", volume)
    with duckdb.connect() as connection:
        with pytest.raises(LoaderError, match="TARGET_POLICY"):
            DuckDBMetadataSink(connection, "main.docs;DROP TABLE other")
        connection.execute("CREATE TABLE documents(other VARCHAR)")
        collect(corpus)
        with pytest.raises(LoaderError, match="TARGET_SCHEMA"):
            publish_sources(
                corpus[2],
                DuckDBMetadataSink(connection, "main.documents"),
                LocalObjects(tmp_path / "objects"),
            )
        assert connection.execute("DESCRIBE documents").fetchone()[0] == "other"
        assert not (tmp_path / "objects").exists()


def test_cli_without_bun(corpus, tmp_path, monkeypatch):
    inv = corpus[3]
    inv["entries"] = []
    corpus[1].write_bytes(encode(inv))
    monkeypatch.setenv("PATH", "")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "fetch",
            "--pack",
            str(corpus[0]),
            "--inventory",
            str(corpus[1]),
            "--output",
            str(corpus[2]),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "publish",
            "--fetched",
            str(corpus[2]),
            "--backend",
            "duckdb",
            "--target",
            "main.documents",
            "--objects",
            str(tmp_path / "objects"),
            "--database",
            str(tmp_path / "empty.duckdb"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_preservation_rights_and_prov_revision_links(corpus, tmp_path):
    from tablespec.document_loader import preservation_metadata, fixity_audit

    collect(corpus)
    collect(corpus, mode="refresh")
    premis, prov = preservation_metadata(corpus[2])
    assert len(premis["objects"]) == 1
    assert premis["rights"][0]["rightsStatement"]["redistribution"] == "unknown"
    assert premis["rights"][0]["basis"] == "operator-supplied-inventory"
    assert [e["eventType"] for e in premis["events"]] == [
        "capture",
        "capture",
        "fixity check",
    ]
    entities = {n["@id"]: n for n in prov["@graph"]}
    assert "urn:sha256:" + digest(BODY) in entities
    projections = [
        n for n in entities.values() if n["@id"].endswith(":documents.jsonl")
    ]
    assert projections[0]["prov:wasDerivedFrom"] == [
        {"@id": "urn:sha256:" + digest(BODY)}
    ]
    assert fixity_audit(corpus[2])["objects"] == 1
    bag = tmp_path / "bag"
    export_bag(corpus[2], bag)
    assert "preservation.json" in (bag / "tagmanifest-sha256.txt").read_text()
    (bag / "provenance.jsonld").write_bytes(b"{}")
    with pytest.raises(LoaderError, match="BAG_FIXITY"):
        validate_bag(bag)


def test_bag_rejects_unmanifested_fifo(corpus, tmp_path):
    import os

    collect(corpus)
    bag = tmp_path / "bag"
    export_bag(corpus[2], bag)
    os.mkfifo(bag / "data" / "unlisted")
    with pytest.raises(LoaderError, match="BAG_FILE_TYPE"):
        validate_bag(bag)


def test_unknown_rights_need_explicit_local_use(corpus):
    with pytest.raises(LoaderError, match="SOURCE_RIGHTS"):
        fetch_sources(corpus[0], corpus[1], corpus[2], opener=transport([Response()]))


def test_duckdb_refuses_wrong_key_without_deleting(corpus, tmp_path):
    from tablespec.document_loader.publish import FIELDS

    collect(corpus)
    with duckdb.connect() as connection:
        ddl = ",".join(
            '"'
            + name
            + '" '
            + ("BIGINT" if kind == "BIGINT" else "VARCHAR")
            + " NOT NULL"
            for name, kind in FIELDS
        )
        connection.execute("CREATE TABLE documents(" + ddl + ", PRIMARY KEY(id))")
        with pytest.raises(LoaderError, match="TARGET_CONSTRAINTS"):
            publish_sources(
                corpus[2],
                DuckDBMetadataSink(connection, "main.documents"),
                LocalObjects(tmp_path / "objects"),
                mode="merge",
            )


def test_atomic_original_no_final_partial_on_rename_failure(tmp_path, monkeypatch):
    from tablespec.document_loader.fetch import immutable_write
    import os

    path = tmp_path / digest(BODY)
    real = os.rename

    def fail(source, destination):
        raise OSError("fixture interruption")

    monkeypatch.setattr(os, "rename", fail)
    with pytest.raises(OSError):
        immutable_write(path, BODY)
    assert not path.exists()
    monkeypatch.setattr(os, "rename", real)
    assert immutable_write(path, BODY)
    assert not immutable_write(path, BODY)


def test_truncated_content_length_keeps_prior_publication(corpus):
    collect(corpus)
    pointer = (corpus[2] / "current.json").read_bytes()
    receipt = collect(
        corpus,
        [Response(BODY, headers={"Content-Length": str(len(BODY) + 100)})],
        mode="refresh",
    )
    assert (
        receipt["status"] == "failed"
        and receipt["items"][0]["code"] == "INCOMPLETE_BODY"
    )
    assert (corpus[2] / "current.json").read_bytes() == pointer


def test_late_chunk_counts_toward_aggregate_budget():
    from tablespec.document_loader.fetch import Transport, DownloadError

    tick = [0.0]

    class Late(Response):
        def read1(self, n):
            tick[0] = 2.0
            return b"12345"

    inv = dict(
        max_total_bytes=5,
        max_bytes=100,
        timeout_ms=1000,
        retries=1,
        request_interval_ms=100,
    )
    calls = []
    transport_client = Transport(
        inv,
        "fixture",
        opener=transport([Late()], calls),
        sleep=lambda _: None,
        clock=lambda: tick[0],
    )
    with pytest.raises(DownloadError, match="TIMEOUT"):
        transport_client.download(
            dict(url="https://court.example.org/a.pdf", media_type="application/pdf")
        )
    assert transport_client.total == 5 and len(calls) == 1
    with pytest.raises(DownloadError, match="BYTE_LIMIT"):
        transport_client.download(
            dict(url="https://court.example.org/b.pdf", media_type="application/pdf")
        )
    assert len(calls) == 1


def test_atomic_pointer_does_not_cleanup_after_success(tmp_path, monkeypatch):
    from tablespec.document_loader.fetch import atomic_write
    from pathlib import Path

    def refuse_unlink(*args, **kwargs):
        raise OSError("post-rename cleanup fixture")

    monkeypatch.setattr(Path, "unlink", refuse_unlink)
    atomic_write(tmp_path, "current.json", b"committed")
    assert (tmp_path / "current.json").read_bytes() == b"committed"


def test_spark_cli_uses_central_factory_application_name(corpus, monkeypatch):
    from tablespec.document_loader import cli
    from types import SimpleNamespace

    collect(corpus)
    calls = []
    session = object()

    def factory(app_name):
        calls.append(app_name)
        return session

    monkeypatch.setattr("tablespec.spark_factory.create_delta_spark_session", factory)

    def sink(active, target):
        assert active is session and target == "catalog.schema.documents"
        return SimpleNamespace(target=target)

    monkeypatch.setattr(cli, "SparkMetadataSink", sink)
    monkeypatch.setattr(cli, "publish_sources", lambda *a, **k: dict(status="complete"))
    assert (
        cli._publish(
            corpus[2],
            "catalog.schema.documents",
            "spark",
            "merge",
            "/Volumes/catalog/schema/originals/collection",
            None,
            None,
            None,
            None,
        )["status"]
        == "complete"
    )
    assert calls == ["tablespec-document-loader"]
