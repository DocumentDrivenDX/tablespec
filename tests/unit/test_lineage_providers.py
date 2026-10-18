"""Tests for tablespec.lineage.providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from tablespec.lineage import DiscoveredUMFProvider, SourceLocationResolver
from tablespec.models.umf import UMF
from tablespec.umf_loader import UMFLoader
from tests.builders import UMFBuilder

pytestmark = pytest.mark.no_spark


def _save(root: Path, rel_dir: str, table: str) -> None:
    UMFLoader().save(UMFBuilder(table).column("id", "INTEGER").build(), root / rel_dir)


def test_discovered_provider_lists_groups_and_tables(tmp_path: Path):
    _save(tmp_path, "customers", "customers")
    _save(tmp_path, "crm/accounts", "accounts")
    provider = DiscoveredUMFProvider(tmp_path)

    assert provider.list_groups() == ["", "crm"]
    assert provider.list_tables("") == ["customers"]
    assert provider.list_tables("crm") == ["accounts"]
    umf = provider.get_umf("crm", "accounts")
    assert umf is not None
    assert umf.table_name == "accounts"
    assert provider.get_umf("", "nope") is None


def _umf(**extra) -> UMF:
    return UMF.model_validate(
        {
            "version": "1.0",
            "table_name": "t",
            "columns": [{"name": "id", "data_type": "INTEGER"}],
            **extra,
        }
    )


def test_resolver_uses_source_directory_then_table_name():
    resolver = SourceLocationResolver()
    folder = resolver.resolve("", _umf(file_format={"source_directory": "inbound/t"}))
    assert folder is not None
    assert folder.source_system == "inbound/t"
    default = resolver.resolve("", _umf())
    assert default is not None
    assert default.source_system == "t"


def test_resolver_prefers_declared_source_path():
    resolver = SourceLocationResolver()
    parquet = resolver.resolve("", _umf(source={"kind": "parquet", "path": "/lake/t"}))
    assert parquet is not None
    assert parquet.source_system == "/lake/t"


def test_resolver_ignores_generated_tables():
    assert SourceLocationResolver().resolve("", _umf(table_type="generated")) is None
