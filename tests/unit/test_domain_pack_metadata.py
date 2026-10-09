"""Tablespec consumes generated UMF structural metadata without executing refs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.domains import (
    get_domain_pack,
    get_run_domain_pack,
    load_domain_pack,
)
from tablespec.sample_data.engine import SampleDataGenerator
from tablespec.sample_data.legal import LEGAL_TYPES
from tablespec.sample_data.streaming import GeneratedDataset, plan_counts
from tests.unit.test_legal_sample_data import EXAMPLE

pytestmark = pytest.mark.no_spark
PACK = EXAMPLE.parent / "domain-pack.json"


def test_portable_pack_runs_and_preserves_unknown_metadata(tmp_path):
    import shutil

    shutil.copytree(PACK.parent, tmp_path / "pack")
    source = json.loads(PACK.read_text())
    source["future"] = {"retained": True}
    path = tmp_path / "pack" / "domain-pack.json"
    path.write_text(json.dumps(source))
    config = GenerationConfig(domain="legal", domain_pack_path=path)
    before = get_domain_pack("legal")
    pack = get_run_domain_pack(config)
    assert pack.metadata == source
    assert pack.registry().domain_types == LEGAL_TYPES
    specs = SampleDataGenerator(EXAMPLE, tmp_path, config).load_umf_files(strict=True)
    data = GeneratedDataset(
        tmp_path / "rows.sqlite", specs, plan_counts(specs, "small"), config
    )
    try:
        data.generate()
        assert data.verified
    finally:
        data.close()
    assert get_domain_pack("legal") is before


@pytest.mark.parametrize("change", ["generator", "version", "method"])
def test_unsupported_metadata_never_imports_code(tmp_path, change):
    source = deepcopy(json.loads(PACK.read_text()))
    if change == "generator":
        source["generator"]["id"] = "uninstalled.module"
    elif change == "version":
        source["generator"]["version"] = "2.0.0"
    else:
        source["domain_types"]["client_name"]["sample_generation"]["method"] = (
            "generate_unknown"
        )
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        load_domain_pack(path)


def test_umf_generated_schema_snapshot():
    schema = (
        Path(__file__).parents[2] / "src/tablespec/sample_data/domain_pack.schema.json"
    )
    assert json.loads(schema.read_text())["$id"] == "urn:umf:domain-pack:1.0.0"
    # Fingerprint the UMF generator output: this is a generated consumer snapshot,
    # not a tablespec schema authority. Refresh through UMF tooling only.
    assert (
        hashlib.sha256(schema.read_bytes()).hexdigest()
        == "e5d74140efa75eae67086dbd1e4bbbca70d2dfe87e688d238b36f45e91e7ab98"
    )


def test_external_metadata_preserved_without_fabricated_fallback(tmp_path):
    from tablespec.sample_data.domains import read_domain_pack

    metadata = {
        "id": "ecology",
        "version": "1.0.0",
        "domain_types": {"observation": {}},
        "sources": {
            "observations": {
                "kind": "external",
                "data_kind": "observed",
                "reference": "https://example.invalid/observations.csv",
                "format": "csv",
                "revision": "release-1",
                "license": {"redistribution": "unknown"},
                "future": {"preserved": True},
            }
        },
        "schemas": [
            {
                "id": "observations",
                "format": "tablespec",
                "reference": "observations.json",
            }
        ],
        "source_bindings": [
            {"schema_id": "observations", "source_id": "observations", "role": "rows"}
        ],
    }
    path = tmp_path / "external.json"
    path.write_text(json.dumps(metadata))
    assert read_domain_pack(path) == metadata
    with pytest.raises(ValueError, match="explicit ingestion"):
        load_domain_pack(path)
    metadata["generator"] = {"id": "tablespec.legal", "version": "1.0.0"}
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="explicit ingestion"):
        load_domain_pack(path)


def test_explicit_generator_registration_for_new_packs(tmp_path):
    from tablespec.sample_data.domains import register_generator_factory
    from tablespec.sample_data.legal import LegalDataGenerators

    register_generator_factory("local.test-legal", "1.0.0", LegalDataGenerators)
    with pytest.raises(ValueError, match="already"):
        register_generator_factory("local.test-legal", "1.0.0", LegalDataGenerators)
    metadata = deepcopy(json.loads(PACK.read_text()))
    metadata["generator"]["id"] = "local.test-legal"
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(metadata))
    assert load_domain_pack(path).generators is LegalDataGenerators
