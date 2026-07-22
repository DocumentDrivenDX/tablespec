"""Tests for configuration resolution (FEAT-034 CFG-01, ADR-019 decision 1).

The contract under test is the precedence order:

    deployment environment  >  connection registry  >  built-in default

plus the requirement that every setting reports which tier supplied it, so a
default that silently filled in is visible rather than assumed.
"""

from __future__ import annotations

import pytest

from profiler.config import (
    DEFAULT,
    DEFAULT_METADATA_CATALOG,
    DEFAULT_METADATA_SCHEMA,
    DEFAULT_OUTPUT_VOLUME,
    DEFAULT_RUNTIME,
    DEPLOYMENT,
    REGISTRY,
    AppConfig,
    get_config,
    reset_config_cache,
    resolve_config,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Keep the process-wide cache from leaking between tests."""
    reset_config_cache()
    yield
    reset_config_cache()


def _registry(tmp_path, **metadata) -> str:
    import yaml

    path = tmp_path / "connections.yaml"
    path.write_text(yaml.safe_dump({"metadata": metadata}), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Precedence


class TestPrecedence:
    def test_deployment_beats_registry(self, tmp_path):
        registry = _registry(tmp_path, catalog="from_registry", schema="reg_schema")
        cfg = resolve_config(
            env={"PROFILER_METADATA_CATALOG": "from_env"}, registry_path=registry
        )
        assert cfg.metadata_catalog == "from_env"
        assert cfg.source_of("metadata_catalog") == DEPLOYMENT
        # The setting the environment did not supply still falls to the registry.
        assert cfg.metadata_schema == "reg_schema"
        assert cfg.source_of("metadata_schema") == REGISTRY

    def test_registry_beats_default(self, tmp_path):
        registry = _registry(tmp_path, catalog="from_registry")
        cfg = resolve_config(env={}, registry_path=registry)
        assert cfg.metadata_catalog == "from_registry"
        assert cfg.source_of("metadata_catalog") == REGISTRY

    def test_default_when_nothing_supplied(self, tmp_path):
        cfg = resolve_config(env={}, registry_path=str(tmp_path / "absent.yaml"))
        assert cfg.metadata_catalog == DEFAULT_METADATA_CATALOG
        assert cfg.metadata_schema == DEFAULT_METADATA_SCHEMA
        assert cfg.output_volume == DEFAULT_OUTPUT_VOLUME
        assert cfg.runtime == DEFAULT_RUNTIME
        assert cfg.source_of("metadata_catalog") == DEFAULT

    def test_blank_env_falls_through(self, tmp_path):
        """An env var set to empty or whitespace must not resolve to ''.

        Clearing a value by blanking it is common in deployment manifests; the
        setting should fall through to the next tier rather than binding the
        app to an empty catalog name.
        """
        registry = _registry(tmp_path, catalog="from_registry")
        cfg = resolve_config(
            env={"PROFILER_METADATA_CATALOG": "   "}, registry_path=registry
        )
        assert cfg.metadata_catalog == "from_registry"
        assert cfg.source_of("metadata_catalog") == REGISTRY

    def test_values_are_stripped(self, tmp_path):
        cfg = resolve_config(
            env={"PROFILER_METADATA_SCHEMA": "  padded  "},
            registry_path=str(tmp_path / "absent.yaml"),
        )
        assert cfg.metadata_schema == "padded"


# ---------------------------------------------------------------------------
# Registry robustness


class TestRegistryRobustness:
    def test_missing_registry_is_not_an_error(self, tmp_path):
        cfg = resolve_config(env={}, registry_path=str(tmp_path / "nope.yaml"))
        assert cfg.metadata_catalog == DEFAULT_METADATA_CATALOG

    def test_malformed_registry_falls_through(self, tmp_path):
        path = tmp_path / "connections.yaml"
        path.write_text("this: [is not: valid: yaml", encoding="utf-8")
        cfg = resolve_config(env={}, registry_path=str(path))
        assert cfg.metadata_catalog == DEFAULT_METADATA_CATALOG

    def test_registry_without_metadata_block(self, tmp_path):
        path = tmp_path / "connections.yaml"
        path.write_text("connections: []\n", encoding="utf-8")
        cfg = resolve_config(env={}, registry_path=str(path))
        assert cfg.metadata_catalog == DEFAULT_METADATA_CATALOG

    def test_non_mapping_metadata_block_ignored(self, tmp_path):
        path = tmp_path / "connections.yaml"
        path.write_text("metadata: just-a-string\n", encoding="utf-8")
        cfg = resolve_config(env={}, registry_path=str(path))
        assert cfg.metadata_catalog == DEFAULT_METADATA_CATALOG


# ---------------------------------------------------------------------------
# Optional settings (DIAG-03 groundwork)


class TestOptionalSettings:
    def test_unset_optionals_are_none(self, tmp_path):
        cfg = resolve_config(env={}, registry_path=str(tmp_path / "absent.yaml"))
        assert cfg.genie_space_id is None
        assert cfg.dashboard_url is None
        assert cfg.spec_volume is None
        assert cfg.warehouse_id is None

    def test_optionals_resolve_from_env(self, tmp_path):
        cfg = resolve_config(
            env={
                "GENIE_SPACE_ID": "space-123",
                "PROFILER_DASHBOARD_URL": "https://example.invalid/d",
                "PROFILER_SPEC_VOLUME": "specs",
                "DATABRICKS_WAREHOUSE_ID": "wh-1",
            },
            registry_path=str(tmp_path / "absent.yaml"),
        )
        assert cfg.genie_space_id == "space-123"
        assert cfg.dashboard_url == "https://example.invalid/d"
        assert cfg.spec_volume == "specs"
        assert cfg.warehouse_id == "wh-1"


# ---------------------------------------------------------------------------
# Derived values


class TestDerived:
    def test_metadata_fqn(self):
        cfg = AppConfig(
            metadata_catalog="c", metadata_schema="s", output_volume="v", runtime="mock"
        )
        assert cfg.metadata_fqn == "c.s"

    def test_output_volume_path(self):
        cfg = AppConfig(
            metadata_catalog="c", metadata_schema="s", output_volume="v", runtime="mock"
        )
        assert cfg.output_volume_path == "/Volumes/c/s/v"

    def test_is_databricks(self, tmp_path):
        absent = str(tmp_path / "absent.yaml")
        assert resolve_config(
            env={"PROFILER_RUNTIME": "databricks"}, registry_path=absent
        ).is_databricks
        assert not resolve_config(
            env={"PROFILER_RUNTIME": "mock"}, registry_path=absent
        ).is_databricks

    def test_runtime_is_lowercased(self, tmp_path):
        cfg = resolve_config(
            env={"PROFILER_RUNTIME": "DATABRICKS"},
            registry_path=str(tmp_path / "absent.yaml"),
        )
        assert cfg.runtime == "databricks"
        assert cfg.is_databricks

    def test_describe_names_home_and_source(self, tmp_path):
        cfg = resolve_config(
            env={"PROFILER_METADATA_CATALOG": "c", "PROFILER_METADATA_SCHEMA": "s"},
            registry_path=str(tmp_path / "absent.yaml"),
        )
        assert "c.s" in cfg.describe()
        assert DEPLOYMENT in cfg.describe()


# ---------------------------------------------------------------------------
# Caching


class TestCaching:
    def test_get_config_is_cached(self):
        first = get_config()
        assert get_config() is first

    def test_reset_clears_cache(self):
        first = get_config()
        reset_config_cache()
        assert get_config() is not first


# ---------------------------------------------------------------------------
# CFG-02 — no environment-identifying literals in defaults


class TestNoEnvironmentLiterals:
    def test_defaults_do_not_name_a_real_environment(self):
        """A default must not smuggle a real address back into tracked source.

        If a default ever names a live catalog or schema, CFG-02 is violated
        through the fallback path rather than through an explicit literal.
        """
        defaults = {
            DEFAULT_METADATA_CATALOG,
            DEFAULT_METADATA_SCHEMA,
            DEFAULT_OUTPUT_VOLUME,
        }
        for banned in ("dev", "test_main_profiler", "prod", "test_main_clinical"):
            assert banned not in defaults
