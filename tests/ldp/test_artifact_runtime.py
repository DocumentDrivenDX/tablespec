"""Artifact identity, closure isolation and replacement regressions."""

from dataclasses import dataclass
import hashlib
import json
import sys
from types import ModuleType
import zipfile

import pytest

from tablespec.ldp.artifact_runtime import (
    ArtifactLoadError,
    load_pinned_callable,
    load_pinned_schema,
)


@dataclass
class Stage:
    entrypoint: str


@dataclass
class Binding:
    artifact_uri: str
    sha256: str
    stages: list[Stage]


def binding(tmp_path, files, *, stages=None):
    path = tmp_path / "adapter.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return Binding(
        path.as_uri(),
        hashlib.sha256(path.read_bytes()).hexdigest(),
        stages or [Stage("adapter.worker.run")],
    )


def test_verified_closure_ignores_ambient_package_and_keeps_original_bytes(
    tmp_path, monkeypatch
):
    ambient = ModuleType("adapter")
    ambient.run = lambda: "ambient"
    monkeypatch.setitem(sys.modules, "adapter", ambient)
    model = binding(
        tmp_path,
        {
            "adapter/__init__.py": "",
            "adapter/helper.py": "VALUE = 9007199254740993\n",
            "adapter/worker.py": "from .helper import VALUE\nimport json\ndef run(): return json.loads(str(VALUE))\n",
        },
    )
    original_path = list(sys.path)
    function = load_pinned_callable(model, "adapter.worker.run")
    (tmp_path / "adapter.zip").write_bytes(b"replaced")
    assert function() == 9007199254740993
    assert sys.path == original_path
    assert sys.modules["adapter"] is ambient
    assert "adapter.worker" not in sys.modules
    with pytest.raises(ArtifactLoadError, match="SHA-256"):
        load_pinned_callable(model, "adapter.worker.run")


def test_undeclared_stage_and_duplicate_stage_refused(tmp_path):
    model = binding(
        tmp_path, {"adapter/__init__.py": "", "adapter/worker.py": "def run(): pass"}
    )
    with pytest.raises(ArtifactLoadError, match="exactly one declared"):
        load_pinned_callable(model, "adapter.worker.other")
    model.stages.append(Stage("adapter.worker.run"))
    with pytest.raises(ArtifactLoadError, match="exactly one declared"):
        load_pinned_callable(model, "adapter.worker.run")


def test_missing_closure_dependency_cannot_use_ambient_module(tmp_path, monkeypatch):
    ambient = ModuleType("not_in_closure")
    ambient.VALUE = "ambient"
    monkeypatch.setitem(sys.modules, "not_in_closure", ambient)
    model = binding(
        tmp_path,
        {
            "adapter/__init__.py": "",
            "adapter/worker.py": "from not_in_closure import VALUE\ndef run(): return VALUE",
        },
    )
    with pytest.raises(ArtifactLoadError, match="failed to load"):
        load_pinned_callable(model, "adapter.worker.run")


@pytest.mark.parametrize(
    "member",
    ["../adapter.py", "/adapter.py", "adapter/../worker.py", "adapter\\worker.py"],
)
def test_unsafe_archive_member_refused(tmp_path, member):
    model = binding(tmp_path, {member: "def run(): pass"})
    with pytest.raises(ArtifactLoadError, match="unsafe"):
        load_pinned_callable(model, "adapter.worker.run")


def test_missing_module_never_falls_back_to_installed_package(tmp_path, monkeypatch):
    ambient = ModuleType("adapter.worker")
    ambient.run = lambda: "ambient"
    monkeypatch.setitem(sys.modules, "adapter.worker", ambient)
    model = binding(tmp_path, {"adapter/__init__.py": ""})
    with pytest.raises(ArtifactLoadError, match="absent"):
        load_pinned_callable(model, "adapter.worker.run")


def test_remote_artifact_not_fetched(tmp_path):
    model = binding(tmp_path, {"adapter/__init__.py": ""})
    model.artifact_uri = "https://example.invalid/adapter.zip"
    with pytest.raises(ArtifactLoadError, match="local file"):
        load_pinned_callable(model, "adapter.worker.run")


@dataclass
class SchemaBinding:
    schema_uri: str
    schema_id: str
    sha256: str


def schema_binding(tmp_path, **changes):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:example:stage:1.0.0",
        "type": "integer",
        **changes,
    }
    data = json.dumps(schema).encode()
    path = tmp_path / "schema.json"
    path.write_bytes(data)
    return SchemaBinding(path.as_uri(), schema["$id"], hashlib.sha256(data).hexdigest())


def test_stage_schema_hash_identity_and_64_bit_contract(tmp_path):
    from jsonschema import Draft202012Validator

    model = schema_binding(tmp_path)
    schema = load_pinned_schema(model)
    Draft202012Validator(schema).validate(9007199254740993)
    model.schema_id = "urn:other"
    with pytest.raises(ArtifactLoadError, match="identity"):
        load_pinned_schema(model)
    model.schema_id = schema["$id"]
    (tmp_path / "schema.json").write_text("{}")
    with pytest.raises(ArtifactLoadError, match="SHA-256"):
        load_pinned_schema(model)


def test_external_schema_reference_is_refused_without_network_access(tmp_path):
    model = schema_binding(tmp_path, **{"$ref": "https://example.invalid/schema"})
    with pytest.raises(ArtifactLoadError, match="self-contained"):
        load_pinned_schema(model)


def test_invalid_schema_is_not_treated_as_typed_stage(tmp_path):
    model = schema_binding(tmp_path, type="not-a-json-type")
    with pytest.raises(ArtifactLoadError, match="not a valid"):
        load_pinned_schema(model)
