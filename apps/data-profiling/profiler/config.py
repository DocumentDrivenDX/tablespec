"""Resolved application configuration (FEAT-034, ADR-019).

Every environment-specific setting the app needs — where metadata lives, which
compute to use, which optional surfaces are enabled — resolves here, once,
through one declared precedence:

    deployment-supplied (environment)  >  connection registry  >  built-in default

ADR-019 decision 1: every surface derives from the single resolved object, so
no two surfaces can disagree about the environment. ADR-019 decision 2: the
metadata home is a declared address, never discovered by scanning for a naming
convention.

Each setting records where its value came from (`AppConfig.sources`) so an
operator can tell a declared value from a default that silently filled in.

This module is deliberately dependency-light — stdlib plus PyYAML — so
configuration can be resolved and tested without a Databricks connection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

import yaml


# ---------------------------------------------------------------------------
# Resolution sources

DEPLOYMENT = "deployment"
REGISTRY = "registry"
DEFAULT = "default"

# Built-in defaults. These are intentionally generic: a default must never
# name a real environment, or CFG-02 leaks environment identity back into
# tracked source through the fallback path.
DEFAULT_METADATA_CATALOG = "main"
DEFAULT_METADATA_SCHEMA = "tablespec_profiler"
DEFAULT_OUTPUT_VOLUME = "ab_runs"
DEFAULT_RUNTIME = "mock"

# Environment variable names, i.e. the deployment-supplied tier. These are the
# declared inputs a deployment sets (app.yaml `env:` for Databricks Apps).
ENV_METADATA_CATALOG = "PROFILER_METADATA_CATALOG"
ENV_METADATA_SCHEMA = "PROFILER_METADATA_SCHEMA"
ENV_OUTPUT_VOLUME = "PROFILER_OUTPUT_VOLUME"
ENV_WAREHOUSE_ID = "DATABRICKS_WAREHOUSE_ID"
ENV_RUNTIME = "PROFILER_RUNTIME"
ENV_GENIE_SPACE_ID = "GENIE_SPACE_ID"
ENV_DASHBOARD_URL = "PROFILER_DASHBOARD_URL"
ENV_SPEC_VOLUME = "PROFILER_SPEC_VOLUME"


# ---------------------------------------------------------------------------
# Resolved configuration


@dataclass(frozen=True)
class AppConfig:
    """One deployment's resolved settings.

    Required settings always hold a value — a built-in default fills in when
    nothing else supplied one. Optional settings are None when unset, and
    per DIAG-03 an unset optional disables only the surface that needs it.
    """

    metadata_catalog: str
    metadata_schema: str
    output_volume: str
    runtime: str
    warehouse_id: Optional[str] = None
    genie_space_id: Optional[str] = None
    dashboard_url: Optional[str] = None
    spec_volume: Optional[str] = None
    sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def metadata_fqn(self) -> str:
        """`catalog.schema` for the declared metadata home."""
        return f"{self.metadata_catalog}.{self.metadata_schema}"

    @property
    def output_volume_path(self) -> str:
        """UC Volume path for run artifacts."""
        return f"/Volumes/{self.metadata_catalog}/{self.metadata_schema}/{self.output_volume}"

    @property
    def is_databricks(self) -> bool:
        return self.runtime == "databricks"

    def source_of(self, setting: str) -> str:
        """Where `setting` was resolved from — deployment, registry, or default."""
        return self.sources.get(setting, DEFAULT)

    def describe(self) -> str:
        """One-line summary of the metadata home, for operator display (DIAG-04)."""
        return f"{self.metadata_fqn} (via {self.source_of('metadata_schema')})"


# ---------------------------------------------------------------------------
# Resolution


def _registry_metadata(path: str) -> dict:
    """Read the optional `metadata:` block from the connection registry.

    A missing or unreadable registry is not an error — it just means the
    registry tier supplies nothing and resolution falls through to defaults.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    meta = cfg.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _pick(
    env: Mapping[str, str],
    env_key: str,
    registry: dict,
    registry_key: str,
    default: Optional[str],
) -> tuple[Optional[str], str]:
    """Resolve one setting, returning (value, source).

    Empty strings are treated as unset so that an env var present-but-blank
    (a common way to "clear" a setting in a deployment manifest) falls through
    rather than resolving to "".
    """
    raw = env.get(env_key)
    if raw and raw.strip():
        return raw.strip(), DEPLOYMENT

    from_registry = registry.get(registry_key)
    if isinstance(from_registry, str) and from_registry.strip():
        return from_registry.strip(), REGISTRY

    return default, DEFAULT


def resolve_config(
    env: Optional[Mapping[str, str]] = None,
    registry_path: str = "connections.yaml",
) -> AppConfig:
    """Resolve one AppConfig through the ADR-019 precedence.

    `env` defaults to the process environment; passing an explicit mapping
    makes resolution testable without mutating os.environ.
    """
    env = os.environ if env is None else env
    registry = _registry_metadata(registry_path)

    sources: dict[str, str] = {}

    def resolve(name: str, env_key: str, registry_key: str, default: Optional[str]):
        value, source = _pick(env, env_key, registry, registry_key, default)
        sources[name] = source
        return value

    metadata_catalog = resolve(
        "metadata_catalog", ENV_METADATA_CATALOG, "catalog", DEFAULT_METADATA_CATALOG
    )
    metadata_schema = resolve(
        "metadata_schema", ENV_METADATA_SCHEMA, "schema", DEFAULT_METADATA_SCHEMA
    )
    output_volume = resolve(
        "output_volume", ENV_OUTPUT_VOLUME, "volume", DEFAULT_OUTPUT_VOLUME
    )
    runtime = resolve("runtime", ENV_RUNTIME, "runtime", DEFAULT_RUNTIME)

    warehouse_id = resolve("warehouse_id", ENV_WAREHOUSE_ID, "warehouse_id", None)
    genie_space_id = resolve(
        "genie_space_id", ENV_GENIE_SPACE_ID, "genie_space_id", None
    )
    dashboard_url = resolve("dashboard_url", ENV_DASHBOARD_URL, "dashboard_url", None)
    spec_volume = resolve("spec_volume", ENV_SPEC_VOLUME, "spec_volume", None)

    # Callers branch on this, so normalize once here rather than at each site.
    assert runtime is not None  # a non-None default is always supplied
    runtime = runtime.lower()

    return AppConfig(
        metadata_catalog=metadata_catalog or DEFAULT_METADATA_CATALOG,
        metadata_schema=metadata_schema or DEFAULT_METADATA_SCHEMA,
        output_volume=output_volume or DEFAULT_OUTPUT_VOLUME,
        runtime=runtime,
        warehouse_id=warehouse_id,
        genie_space_id=genie_space_id,
        dashboard_url=dashboard_url,
        spec_volume=spec_volume,
        sources=sources,
    )


_cached: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Process-wide resolved configuration.

    Resolved once and reused: Streamlit re-runs the script on every interaction,
    and re-reading the registry from disk each time would be wasted I/O.
    """
    global _cached
    if _cached is None:
        _cached = resolve_config()
    return _cached


def reset_config_cache() -> None:
    """Drop the cached config. For tests, and for a deliberate reload."""
    global _cached
    _cached = None
