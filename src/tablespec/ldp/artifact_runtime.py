# SPDX-License-Identifier: MIT OR Apache-2.0
"""Load declared Python stages from an immutable local adapter ZIP.

This is artifact identity and import isolation, not a sandbox for hostile code.
Operators authorize executable adapters separately. Remote artifact resolution
belongs to deployment; this loader never fetches or extracts an archive.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import json
import keyword
from pathlib import Path, PurePosixPath
import stat
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import unquote, urlsplit
import zipfile

if TYPE_CHECKING:
    from tablespec.ldp.capability import ExternalTransformBinding, TypedSchemaBinding


class ArtifactLoadError(ValueError):
    """The declared executable could not be loaded from its pinned artifact."""


def load_pinned_schema(binding: TypedSchemaBinding) -> dict[str, Any]:
    """Verify a local, self-contained Draft 2020-12 stage schema.

    External references require a separately pinned resolution contract and are
    refused here; schema validation must not fetch ambient network resources.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        data = _local_path(binding.schema_uri).read_bytes()
    except OSError as error:
        raise ArtifactLoadError("pinned local schema is unavailable") from error
    if hashlib.sha256(data).hexdigest() != binding.sha256:
        raise ArtifactLoadError("schema SHA-256 differs from its declared hash")
    try:
        schema = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise ArtifactLoadError("pinned schema is not JSON") from error
    if not isinstance(schema, dict) or schema.get("$id") != binding.schema_id:
        raise ArtifactLoadError("schema identity differs from its declared schema_id")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ArtifactLoadError("stage schema must declare JSON Schema Draft 2020-12")

    def check_references(value: Any) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                if name in ("$ref", "$dynamicRef") and (
                    not isinstance(child, str) or not child.startswith("#")
                ):
                    raise ArtifactLoadError(
                        "stage schema references must be self-contained"
                    )
                check_references(child)
        elif isinstance(value, list):
            for child in value:
                check_references(child)

    check_references(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ArtifactLoadError(
            "stage schema is not a valid Draft 2020-12 schema"
        ) from error
    return schema


def _local_path(uri: str) -> Path:
    parsed = urlsplit(uri)
    if parsed.query or parsed.fragment:
        raise ArtifactLoadError("artifact URI must not contain a query or fragment")
    if parsed.scheme == "file" and parsed.netloc in ("", "localhost"):
        path = Path(unquote(parsed.path))
    elif not parsed.scheme and not parsed.netloc:
        path = Path(uri)
    else:
        raise ArtifactLoadError(
            "resolve the pinned artifact to a local file before loading"
        )
    if not path.is_absolute():
        raise ArtifactLoadError("artifact path must be absolute")
    return path


class _ArchiveModules:
    """A private module cache: artifact packages never enter sys.modules."""

    def __init__(self, data: bytes, digest: str) -> None:
        self.files: dict[str, bytes] = {}
        self.modules: dict[str, ModuleType] = {}
        self.digest = digest
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                seen: set[str] = set()
                for member in archive.infolist():
                    name = member.filename
                    parts = PurePosixPath(name).parts
                    if (
                        not parts
                        or name.startswith("/")
                        or "\\" in name
                        or any(
                            part in (".", "..") for part in name.rstrip("/").split("/")
                        )
                        or name in seen
                        or stat.S_ISLNK(member.external_attr >> 16)
                        or member.flag_bits & 1
                    ):
                        raise ArtifactLoadError(
                            "artifact contains an unsafe or duplicate member"
                        )
                    seen.add(name)
                    if not member.is_dir():
                        self.files[name] = archive.read(member)
        except (zipfile.BadZipFile, RuntimeError, OSError) as error:
            raise ArtifactLoadError(
                "artifact is not a readable unencrypted ZIP"
            ) from error
        self.roots = {
            name.split("/")[0].removesuffix(".py")
            for name in self.files
            if name.endswith(".py")
        }
        if self.roots & sys.stdlib_module_names:
            raise ArtifactLoadError(
                "artifact must not shadow a Python standard-library package"
            )

    def _member(self, name: str) -> tuple[str, bool]:
        base = name.replace(".", "/")
        if f"{base}/__init__.py" in self.files:
            return f"{base}/__init__.py", True
        if f"{base}.py" in self.files:
            return f"{base}.py", False
        raise ArtifactLoadError("declared module is absent from the pinned artifact")

    def load(self, name: str) -> ModuleType:
        if name in self.modules:
            return self.modules[name]
        member, package = self._member(name)
        parent_name, _, child_name = name.rpartition(".")
        parent = self.load(parent_name) if parent_name else None
        module = ModuleType(name)
        module.__file__ = f"pinned-zip:{self.digest}!/{member}"
        module.__package__ = name if package else parent_name
        if package:
            module.__path__ = [f"pinned-zip:{self.digest}!/{name.replace('.', '/')}"]
        module.__dict__["__builtins__"] = {
            **vars(builtins),
            "__import__": self.import_module,
        }
        self.modules[name] = module
        if parent is not None:
            setattr(parent, child_name, module)
        try:
            exec(compile(self.files[member], module.__file__, "exec"), module.__dict__)
        except Exception as error:
            self.modules.pop(name, None)
            if parent is not None:
                delattr(parent, child_name)
            raise ArtifactLoadError("pinned artifact module failed to load") from error
        return module

    def import_module(
        self,
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        if level:
            package = (globals or {}).get("__package__", "")
            name = importlib.util.resolve_name("." * level + name, package)
        root = name.split(".")[0]
        if root not in self.roots:
            if root not in sys.stdlib_module_names:
                raise ArtifactLoadError(
                    "adapter dependency is absent from the pinned closure"
                )
            return builtins.__import__(name, globals, locals, fromlist, 0)
        module = self.load(name)
        if fromlist:
            for child in fromlist:
                if child != "*" and not hasattr(module, child):
                    setattr(module, child, self.load(f"{name}.{child}"))
            return module
        return self.load(root)


def load_pinned_callable(
    binding: ExternalTransformBinding, entrypoint: str
) -> Callable[..., Any]:
    """Load exactly one declared stage, with no ambient application fallback.

    Each returned callable retains an in-memory snapshot of the verified ZIP.
    Subsequent replacement of its on-disk artifact cannot change that callable.
    Adapter imports use a private namespace, so two artifact versions coexist
    without replacing application modules or modifying the process import path.
    Data bounds and typed stage input/output checks belong to the generated flow.
    """
    if sum(stage.entrypoint == entrypoint for stage in binding.stages) != 1:
        raise ArtifactLoadError("entrypoint must identify exactly one declared stage")
    parts = entrypoint.split(".")
    if len(parts) < 2 or any(
        not p.isidentifier() or keyword.iskeyword(p) for p in parts
    ):
        raise ArtifactLoadError("entrypoint must be a qualified Python module function")
    try:
        data = _local_path(binding.artifact_uri).read_bytes()
    except OSError as error:
        raise ArtifactLoadError("pinned local artifact is unavailable") from error
    if hashlib.sha256(data).hexdigest() != binding.sha256:
        raise ArtifactLoadError(
            "artifact SHA-256 differs from its declared closure hash"
        )
    modules = _ArchiveModules(data, binding.sha256)
    module = modules.load(".".join(parts[:-1]))
    function = getattr(module, parts[-1], None)
    if not callable(function):
        raise ArtifactLoadError(
            "declared entrypoint is not a callable in the pinned artifact"
        )
    return function
