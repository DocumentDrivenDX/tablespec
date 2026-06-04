"""Seed e2e tests (item 4: sample_data_seeds) -- AC4.2, AC4.3, AC4.5.

UMF set -> run the REAL ``SampleDataGenerator`` into a temp dir -> emit dbt seeds
(``tablespec.dbt.seeds``) + a ``seeds:`` ``column_types`` config -> real ``dbt
seed`` / ``dbt build`` on duckdb -> query the warehouse and assert on actual
catalog types and rows. The NEGATIVE path (AC4.5) is an explicit must-fail:

  * AC4.2 ``dbt seed`` loads each CSV; the duckdb catalog column types EQUAL the
    configured ``column_types``.
  * AC4.3 a downstream model ``ref()``s the seed and ``dbt build`` SUCCEEDS;
    querying the model returns the seeded rows.
  * AC4.5 (NEGATIVE) a non-numeric value injected into the INTEGER ``member_id``
    column -> ``dbt seed`` FAILS (cast/load error), exit code non-zero.

dbt(+duckdb) required; skips if absent. JVM-free, slow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.slow]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for seed e2e")
pytest.importorskip("dbt", reason="dbt-core required for seed e2e")

from tablespec.dbt.seeds import emit_seeds, render_seeds_config  # noqa: E402
from tablespec.sample_data.config import GenerationConfig  # noqa: E402
from tablespec.sample_data.engine import SampleDataGenerator  # noqa: E402
from tablespec.umf_loader import UMFLoader  # noqa: E402

FIX = Path(__file__).parent.parent / "fixtures" / "dbt_roadmap" / "sample_seeds"
PROJECT = "tablespec_seeds"


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


def _load_umfs() -> list:
    loader = UMFLoader()
    return [loader.load(p) for p in sorted((FIX / "tables").glob("*.json"))]


def _dbt_project_yml(seeds_block: str) -> str:
    return (
        f"name: '{PROJECT}'\n"
        "version: '1.0.0'\n"
        "config-version: 2\n"
        f"profile: '{PROJECT}'\n"
        'model-paths: ["models"]\n'
        'seed-paths: ["seeds"]\n'
        'target-path: "target"\n'
        'clean-targets: ["target", "dbt_packages"]\n'
        "\n" + seeds_block
    )


def _profiles_yml() -> str:
    return (
        f"{PROJECT}:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        "      path: \"{{ env_var('DBT_DUCKDB_PATH', 'seeds.duckdb') }}\"\n"
        "      threads: 1\n"
    )


# A downstream model that ref()s the member seed (AC4.3).
_DOWNSTREAM_MODEL = (
    "{{ config(materialized='table') }}\n\n"
    "SELECT member_id, premium_amount, enrolled_on, full_name\n"
    "FROM {{ ref('member') }}\n"
)


def _build_seed_project(
    mutate=None, column_types_override=None
) -> tuple[Path, Path, int]:
    """Generate real data, emit seeds, assemble a dbt project on disk.

    Returns (project_dir, duckdb_path, seeded_row_count). ``mutate(seed_text)``
    may transform the member seed CSV before it is written (data negative path);
    ``column_types_override(types)`` may transform the per-table column_types
    mapping before the ``seeds:`` config is rendered (config negative path).
    """
    project = Path(tempfile.mkdtemp(prefix="tablespec_seeds_"))
    generated = project / "_generated"
    generated.mkdir()

    gen = SampleDataGenerator(
        FIX, generated, GenerationConfig(num_members=12, random_seed=42)
    )
    assert gen.run_generation() is True

    umfs = _load_umfs()
    artifacts = emit_seeds(umfs, generated)
    column_types = artifacts.column_types
    if column_types_override is not None:
        column_types = column_types_override(column_types)
    seeds_block = render_seeds_config(column_types, project_name=PROJECT)

    (project / "seeds").mkdir()
    (project / "models").mkdir()
    member_csv = artifacts.files["seeds/member.csv"]
    row_count = len(member_csv.splitlines()) - 1  # minus header
    if mutate is not None:
        member_csv = mutate(member_csv)
    for rel, text in artifacts.files.items():
        if rel == "seeds/member.csv":
            text = member_csv
        (project / rel).write_text(text)

    (project / "models" / "member_enriched.sql").write_text(_DOWNSTREAM_MODEL)
    (project / "dbt_project.yml").write_text(_dbt_project_yml(seeds_block))
    (project / "profiles.yml").write_text(_profiles_yml())

    db = project / "seeds.duckdb"
    return project, db, row_count


def _dbt(project: Path, db: Path, *cmd: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, DBT_DUCKDB_PATH=str(db))
    return subprocess.run(
        ["dbt", *cmd, "--profiles-dir", str(project), "--project-dir", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


# ---------------------------------------------------------------------------
# AC4.2 dbt seed loads CSV with the configured column types
# ---------------------------------------------------------------------------


def test_seed_loads_with_types() -> None:
    """AC4.2: ``dbt seed`` creates the member seed table and the duckdb catalog
    column types EQUAL the configured ``column_types``."""
    _require_dbt()
    project, db, _ = _build_seed_project()
    try:
        seeded = _dbt(project, db, "seed")
        assert seeded.returncode == 0, (
            f"dbt seed should succeed:\n{seeded.stdout}\n{seeded.stderr}"
        )
        con = _connect(db)
        try:
            rows = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name='member' ORDER BY ordinal_position"
            ).fetchall()
        finally:
            con.close()
        catalog = dict(rows)
        # The configured column_types (DECIMAL(18,2), DATE, INTEGER) survive in the
        # duckdb catalog. NOTE: the config declares full_name as VARCHAR(64) but
        # duckdb's catalog NORMALIZES a length-bounded VARCHAR back to bare VARCHAR
        # -- so this column asserts the duckdb-normalized type, not the literal
        # config string. The other three are reported verbatim.
        assert catalog["member_id"] == "INTEGER", catalog
        assert catalog["premium_amount"] == "DECIMAL(18,2)", catalog
        assert catalog["enrolled_on"] == "DATE", catalog
        assert catalog["full_name"] == "VARCHAR", (
            catalog
        )  # duckdb-normalized VARCHAR(64)
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC4.3 a downstream model ref()s the seed and builds
# ---------------------------------------------------------------------------


def test_seed_downstream_ref_builds() -> None:
    """AC4.3: a model ``ref()``s the member seed; ``dbt build`` SUCCEEDS and the
    model returns the seeded rows (same count, real values)."""
    _require_dbt()
    project, db, seeded_rows = _build_seed_project()
    try:
        built = _dbt(project, db, "build")
        assert built.returncode == 0, (
            f"dbt build (seed + downstream ref) should succeed:\n"
            f"{built.stdout}\n{built.stderr}"
        )
        con = _connect(db)
        try:
            (model_count,) = con.execute(
                "SELECT count(*) FROM member_enriched"
            ).fetchone()
            (seed_count,) = con.execute("SELECT count(*) FROM member").fetchone()
            # A real seeded value survives the ref()-built model.
            sample = con.execute(
                "SELECT member_id FROM member_enriched ORDER BY member_id LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        assert model_count == seeded_rows > 0, (model_count, seeded_rows)
        assert seed_count == seeded_rows, (seed_count, seeded_rows)
        assert isinstance(sample[0], int), sample
    finally:
        shutil.rmtree(project, ignore_errors=True)


# ---------------------------------------------------------------------------
# AC4.5 (NEGATIVE) wrong column_type -> dbt seed FAILS
# ---------------------------------------------------------------------------


def test_seed_wrong_type_fails() -> None:
    """AC4.5 (NEGATIVE): a non-numeric value injected into the INTEGER
    ``member_id`` column -> ``dbt seed`` FAILS (cast/load error)."""
    _require_dbt()

    def _inject_bad_member_id(csv_text: str) -> str:
        lines = csv_text.splitlines()
        header, first, *rest = lines
        cols = first.split(",")
        cols[0] = "NOT_AN_INT"  # member_id is the first (INTEGER) column
        return "\n".join([header, ",".join(cols), *rest]) + "\n"

    project, db, _ = _build_seed_project(mutate=_inject_bad_member_id)
    try:
        seeded = _dbt(project, db, "seed")
        assert seeded.returncode != 0, (
            "dbt seed MUST fail when an INTEGER column holds a non-numeric value "
            f"but it succeeded:\n{seeded.stdout}\n{seeded.stderr}"
        )
        combined = (seeded.stdout + seeded.stderr).lower()
        # A real type/cast failure (not just any error): duckdb reports a
        # conversion error naming the INTEGER column it could not load.
        assert "conversion" in combined or "convert" in combined, seeded.stdout
        assert "member_id" in combined or "integer" in combined, seeded.stdout
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_seed_wrong_column_type_config_fails() -> None:
    """AC4.5 (NEGATIVE, config variant): a WRONG ``column_types`` config -- declaring
    the VARCHAR ``full_name`` column as INTEGER -- makes ``dbt seed`` FAIL trying to
    load the (correct, real) string values into an INTEGER column."""
    _require_dbt()

    def _mistype_full_name(types: dict) -> dict:
        out = {t: dict(cols) for t, cols in types.items()}
        out["member"]["full_name"] = "INTEGER"  # real values are names, not ints
        return out

    project, db, _ = _build_seed_project(column_types_override=_mistype_full_name)
    try:
        seeded = _dbt(project, db, "seed")
        assert seeded.returncode != 0, (
            "dbt seed MUST fail when column_types declares a VARCHAR column as "
            f"INTEGER but it succeeded:\n{seeded.stdout}\n{seeded.stderr}"
        )
        combined = (seeded.stdout + seeded.stderr).lower()
        assert "conversion" in combined or "convert" in combined, seeded.stdout
        assert "full_name" in combined or "integer" in combined, seeded.stdout
    finally:
        shutil.rmtree(project, ignore_errors=True)
