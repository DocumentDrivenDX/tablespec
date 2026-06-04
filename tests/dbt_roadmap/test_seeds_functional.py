"""Seed-emitter functional tests (item 4: sample_data_seeds) -- AC4.1, AC4.4.

These prove the seed emitter (``tablespec.dbt.seeds``) consumes the REAL output of
the EXISTING ``SampleDataGenerator`` (run into a temp ``output_dir`` in the test --
no hand-written seed fixtures) and produces dbt-loadable ``seeds/<t>.csv`` with the
SAME rows/values re-encoded comma-delimited, plus a ``column_types`` mapping
derived from the UMF contract facts.

No dbt-core / duckdb needed here (pure text). JVM-free, fast.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from tablespec.dbt.seeds import (
    SeedEmitterError,
    emit_seeds,
    render_seeds_config,
    seed_column_types,
)
from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.engine import SampleDataGenerator
from tablespec.umf_loader import UMFLoader

pytestmark = [pytest.mark.no_spark]

FIX = Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "sample_seeds"


def _load_umfs() -> list:
    loader = UMFLoader()
    return [loader.load(p) for p in sorted((FIX / "tables").glob("*.json"))]


def _generate(out_dir: Path) -> None:
    """Run the REAL generator (AC4.4) over the fixture UMF set into *out_dir*."""
    gen = SampleDataGenerator(
        FIX, out_dir, GenerationConfig(num_members=12, random_seed=42)
    )
    assert gen.run_generation() is True


def _parse_generated(out_dir: Path, table: str, delimiter: str = "|") -> list[dict]:
    """Parse the generator's delimited output as {umf_name: value} rows.

    Reads via the same ``<table>.txt`` handle the emitter resolves, mapping the
    canonical-name header back to UMF column names for value comparison.
    """
    umf = next(u for u in _load_umfs() if u.table_name == table)
    data = umf.model_dump(exclude_none=True)
    header_to_name = {}
    for col in data["columns"]:
        header_to_name[col.get("canonical_name") or col["name"]] = col["name"]
    text = (out_dir / f"{table}.txt").read_text()
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [{header_to_name[h]: r[h] for h in reader.fieldnames} for r in reader]


def _parse_seed(seed_csv: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(seed_csv)))


def test_seed_emitter_files_and_column_types(tmp_path: Path) -> None:
    """AC4.1 + AC4.4: real generated data -> ``seeds/<t>.csv`` with the SAME
    rows/values (comma-delimited, header = UMF names) and ``column_types`` derived
    from UMF."""
    out = tmp_path / "generated"
    _generate(out)
    umfs = _load_umfs()

    artifacts = emit_seeds(umfs, out)

    # AC4.1: one seeds/<t>.csv per table, header = UMF column names.
    for umf in umfs:
        rel = f"seeds/{umf.table_name}.csv"
        assert rel in artifacts.files, artifacts.files.keys()
        seed_rows = _parse_seed(artifacts.files[rel])
        gen_rows = _parse_generated(out, umf.table_name)

        # Same rows/values (re-encoded): header = UMF names, every value identical.
        assert seed_rows == gen_rows, (
            f"seed rows must equal the generated rows for {umf.table_name}"
        )
        assert len(seed_rows) > 0, "real generated data must be non-empty"
        data_names = [
            c["name"]
            for c in umf.model_dump(exclude_none=True)["columns"]
            if c.get("source", "data") == "data"
        ]
        # Seed header uses UMF column names (NOT canonical_name).
        assert list(_parse_seed(artifacts.files[rel])[0].keys()) == data_names

    # AC4.1: column_types derived from UMF (the contract type mapping).
    member_types = artifacts.column_types["member"]
    assert member_types == {
        "member_id": "INTEGER",
        "premium_amount": "DECIMAL(18,2)",
        "enrolled_on": "DATE",
        "full_name": "VARCHAR(64)",
    }


def test_seed_column_types_helper_matches_contract() -> None:
    """``seed_column_types`` derives the SAME adapter types as the model contract
    (only the generated data columns appear)."""
    umf = next(u for u in _load_umfs() if u.table_name == "member")
    assert seed_column_types(umf) == {
        "member_id": "INTEGER",
        "premium_amount": "DECIMAL(18,2)",
        "enrolled_on": "DATE",
        "full_name": "VARCHAR(64)",
    }


def test_render_seeds_config_yaml_shape() -> None:
    """The ``seeds:`` block nests ``+column_types`` per table under the project,
    quoting parametrized SQL types so the result is valid YAML for dbt_project.yml."""
    import yaml

    block = render_seeds_config(
        {"member": {"member_id": "INTEGER", "premium_amount": "DECIMAL(18,2)"}},
        project_name="tablespec_gold",
    )
    parsed = yaml.safe_load(block)
    assert parsed == {
        "seeds": {
            "tablespec_gold": {
                "member": {
                    "+column_types": {
                        "member_id": "INTEGER",
                        "premium_amount": "DECIMAL(18,2)",
                    }
                }
            }
        }
    }


def test_emit_seeds_missing_file_raises(tmp_path: Path) -> None:
    """NEGATIVE (functional): a UMF with no generated file -> SeedEmitterError
    (the emitter never silently emits an empty seed)."""
    umfs = _load_umfs()
    with pytest.raises(SeedEmitterError, match="No generated sample file"):
        emit_seeds(umfs, tmp_path)  # empty dir -> nothing generated


def test_emit_seeds_unknown_header_raises(tmp_path: Path) -> None:
    """NEGATIVE (functional): a generated file whose header carries a column not in
    the UMF data columns -> SeedEmitterError (never silently re-encode a column the
    contract does not know about)."""
    umf = next(u for u in _load_umfs() if u.table_name == "member")
    # Hand-write a generated file with an EXTRA, unknown header column.
    (tmp_path / "member.txt").write_text(
        "member_id|premium_amount|enrolled_on|MemberName|mystery\n"
        "1|2.00|2024-01-01|Alice|x\n"
    )
    with pytest.raises(SeedEmitterError, match="not present in the UMF data columns"):
        emit_seeds([umf], tmp_path)


def test_seed_column_types_excludes_non_data_columns() -> None:
    """``column_types`` covers ONLY the generated data columns: a filename-sourced
    column (which the generator never writes to the file) is excluded."""
    from tablespec.models.umf import UMF

    umf = UMF(
        version="1.0",
        table_name="t",
        columns=[
            {"name": "id", "data_type": "INTEGER", "nullable": {"default": False}},
            {"name": "src_file", "data_type": "VARCHAR", "source": "filename"},
        ],
    )
    types = seed_column_types(umf)
    assert types == {"id": "INTEGER"}, types
