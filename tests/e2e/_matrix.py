"""Shared backbone-matrix assertions reused by the spark + no_spark lanes.

Both lanes compile the SAME fixture UMF set and run the SAME backbone; they differ
only in the execution backend (and therefore the pytest marker). Keeping the
per-backend assertions here means the two lane modules stay thin and the contract
("compiled artifacts are runtime-loadable; clean data -> valid; transforms produce
the expected output, byte-identical across engines") is asserted identically on
every leg.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from tablespec.e2e.backbone import (
    canonical_ingested,
    make_engine,
    run_backbone,
)
from tablespec.e2e.compile import compile_umfs
from tablespec.e2e.manifest import CompiledArtifacts
from tablespec.e2e.paths import umfs_from_specs

from tests.e2e.conftest import FIXTURES, GOLD_TARGETS, RAW_BATCHES, SPECS

#: Committed cross-engine canonical ingest goldens (one per ingested fixture table).
#: Every backend's canonical ingest MUST be byte-identical to these; that ties the
#: spark / sail / duckdb legs to the SAME bytes without cross-lane imports.
CANONICAL_GOLDEN_DIR = FIXTURES / "canonical"


def compile_fixture_set(out_dir: Path) -> CompiledArtifacts:
    """Compile the shared member/claims/claim_enriched fixture set under *out_dir*."""
    umfs = umfs_from_specs(SPECS)
    return compile_umfs(
        umfs, out_dir, source="specs", gold_targets=GOLD_TARGETS
    )


def assert_artifacts_runtime_loadable(artifacts: CompiledArtifacts) -> None:
    """Every compiled artifact is a self-sufficient runtime contract on disk.

    Proves (without any engine) that the schema artifacts LOAD: the JSON schema
    parses, the PySpark ``StructType`` source imports + evaluates to a schema object,
    and the manifest round-trips purely from ``manifest.json``.
    """
    # The manifest round-trips from disk alone (the backbone runs from it).
    reloaded = CompiledArtifacts.load(artifacts.root)
    assert reloaded.source == artifacts.source
    assert set(reloaded.tables) == set(artifacts.tables)

    for name, ta in artifacts.tables.items():
        # JSON schema artifact parses.
        schema = json.loads(ta.json_schema.read_text())
        assert isinstance(schema, dict) and schema, f"{name}: empty JSON schema"

        # PySpark schema artifact is importable Python that yields a StructType.
        struct = _load_pyspark_struct(ta.pyspark_schema)
        field_names = [f.name for f in struct.fields]
        assert field_names, f"{name}: pyspark schema has no fields"

        # DDL + ingest SQL are present and non-trivial.
        assert ta.ddl_sql.read_text().strip(), f"{name}: empty DDL"
        assert "MERGE INTO" in ta.ingest_sql.read_text(), f"{name}: no transform"

        # The compiled validation suite is a non-empty expectation list.
        suite = json.loads(ta.suite_json.read_text())
        assert isinstance(suite, list) and suite, f"{name}: empty suite"


def _load_pyspark_struct(schema_py: Path) -> Any:
    """Import the compiled ``schemas/<t>.schema.py`` and return its StructType.

    The artifact is PySpark ``StructType`` *source*; loading it proves the compiled
    schema is runtime-usable. The module exposes the schema under a conventional
    name (``schema``) or as the sole module-level ``StructType``.
    """
    spec = importlib.util.spec_from_file_location(
        f"_compiled_schema_{schema_py.stem}", schema_py
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from pyspark.sql.types import StructType

    if hasattr(module, "schema") and isinstance(module.schema, StructType):
        return module.schema
    for value in vars(module).values():
        if isinstance(value, StructType):
            return value
    raise AssertionError(f"no StructType found in compiled schema {schema_py}")


def run_full_backbone(
    artifacts: CompiledArtifacts, *, backend: str, spark: Any
) -> None:
    """Run the whole backbone for *backend* and assert every stage is green.

    Asserts the aggregate result AND each individual stage so a regression names the
    failing stage (ingest / validate / transform / dbt parse / gold-plan / ldp).
    """
    result = run_backbone(
        artifacts, spark=spark, raw_batches=RAW_BATCHES, backend=backend
    )
    failed = [f"{s.name}: {s.detail}" for s in result.stages if not s.ok]
    assert not failed, f"[{backend}] backbone stages failed:\n" + "\n".join(failed)
    assert result.ok

    # The clean fixture data MUST validate: every ``validate:*`` stage scanned the
    # compiled suite over the raw/ingested rows and passed.
    validate_stages = [s for s in result.stages if s.name.startswith(f"[{backend}] validate:")]
    assert validate_stages, f"[{backend}] no validation stage ran"
    assert all(s.ok for s in validate_stages)

    # dbt parse (offline manifest) ran for every compiled project -> the compiled dbt
    # artifacts are runtime-loadable.
    parse_stages = [s for s in result.stages if s.name.startswith("dbt parse:")]
    assert parse_stages, "no dbt parse stage ran"
    assert all("manifest=written" in s.detail for s in parse_stages)


def canonical_ingest(backend: str, *, spark: Any, out_dir: Path) -> dict[str, str]:
    """Compile + ingest the fixture set on *backend*; return per-table canonical JSON.

    The returned mapping ``{table: canonical_json}`` is the cross-engine byte-parity
    surface: two backends agree iff these strings are byte-identical (reusing the
    shared ``canonical.to_json`` the conformance matrix uses).
    """
    artifacts = compile_fixture_set(out_dir)
    engine = make_engine(backend, spark=spark)
    out: dict[str, str] = {}
    for table, batches in RAW_BATCHES.items():
        out[table] = canonical_ingested(engine, artifacts, table, batches)
    return out


def assert_canonical_matches_golden(backend: str, canon: dict[str, str]) -> None:
    """Assert *backend*'s canonical ingest is byte-identical to the committed golden.

    Comparing every backend to the SAME on-disk golden ties the spark / sail / duckdb
    legs to identical bytes (transitive parity) without one lane importing another.
    """
    for table, actual in canon.items():
        golden = (CANONICAL_GOLDEN_DIR / f"{table}.ingested.canonical.json").read_text()
        assert actual == golden, (
            f"[{backend}] {table}: canonical ingest diverged from the committed "
            f"golden\n--- actual ---\n{actual}\n--- golden ---\n{golden}"
        )
