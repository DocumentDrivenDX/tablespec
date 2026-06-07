"""Phase 5: multi-table GOLD dbt project -- DAG audit + semantic equivalence.

This exercises ``generate_dbt_dag_project`` end to end on a small FK-linked fixture
set (``member`` <- ``claims`` -> gold ``member_claims``) and proves the corrected
design's load-bearing claims:

  * **STATIC REFS / manifest audit.** Generate the project, build the raw landing
    tables in duckdb, run ``dbt parse`` + ``dbt compile`` + ``dbt run``, then read
    ``manifest.json`` and assert the model dependency edges (``parent_map``) are
    EXACTLY the logical edges the IR predicts -- no missing deps, no phantom
    ``source('external')`` edges.
  * **SEMANTIC EQUIVALENCE.** Compile+run the gold model, then run the *literal*
    ``SQLPlanGenerator`` temp-view plan (the historical direct path) over the SAME
    ingested staging tables, and assert the two canonical row sets are
    byte-identical. Same generator, two renderers (dbt ref vs literal) -> same data.

dbt/duckdb are required; the test skips if the dbt CLI is unavailable.
"""

# dbt project emitter coverage.
# @covers US-025-AC1
# @covers US-025-AC2
# @covers US-025-AC3
# @covers US-025-AC4
# @covers US-025-AC5

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

# dbt(+duckdb) integration: no Spark/JVM required. Marked no_spark so the
# fast/JVM-free lane can run it (it still skips if the dbt CLI is absent).
pytestmark = [pytest.mark.no_spark]

duckdb = pytest.importorskip("duckdb", reason="duckdb required for dbt dag tests")
pytest.importorskip("dbt", reason="dbt-core required for dbt dag tests")

from tablespec.dbt import generate_dbt_dag_project  # noqa: E402
from tablespec.dbt.registry import NodeRegistry  # noqa: E402
from tablespec.models.umf import UMF  # noqa: E402
from tablespec.schemas.sql_generator import generate_sql_plan  # noqa: E402

from tests.ingest_parity.canonical import to_json  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dbt_dag"
TABLES = ["member", "claims", "member_claims"]
STAGING = {
    "member": ["member_id", "member_name", "state"],
    "claims": ["claim_id", "member_id", "claim_amount"],
}
GOLD_TABLE = "member_claims"
GOLD_COLUMNS = ["claim_id", "member_id", "claim_amount", "member_name", "member_state"]
GOLD_SCALES = {"claim_amount": 2}

# The logical edges the IR predicts (model -> its parents), used to audit the
# dbt-built manifest. Pure model<-model / model<-source dependency graph.
EXPECTED_MODEL_PARENTS = {
    "gold_member_claims": {"ingested_claims", "ingested_member"},
    "ingested_claims": {"raw_claims"},
    "ingested_member": {"raw_member"},
}


def _load_umfs() -> list[UMF]:
    return [
        UMF(**yaml.safe_load((FIXTURE_DIR / f"{t}.umf.yaml").read_text()))
        for t in TABLES
    ]


def _connect(db: Path):
    con = duckdb.connect(str(db))
    con.execute("SET TimeZone='UTC'")
    return con


def _load_raw_tables(db: Path) -> None:
    """Create the all-STRING ``raw_<t>`` landing tables from the fixture CSVs."""
    con = _connect(db)
    try:
        for t, cols in STAGING.items():
            coldefs = ", ".join(f'"{c}" VARCHAR' for c in cols)
            coldefs += ', "_source_file" VARCHAR, "_load_ts" TIMESTAMP'
            con.execute(f"CREATE TABLE raw_{t} ({coldefs})")
            proj = ", ".join(f'"{c}"' for c in cols)
            proj += ', "_source_file", cast("_load_ts" as timestamp)'
            csv = FIXTURE_DIR / f"{t}.raw.csv"
            con.execute(
                f"INSERT INTO raw_{t} SELECT {proj} "
                f"FROM read_csv_auto('{csv}', header=true, all_varchar=true)"
            )
    finally:
        con.close()


def _dbt(project: Path, db: Path, *cmd: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, DBT_DUCKDB_PATH=str(db))
    return subprocess.run(
        ["dbt", *cmd, "--profiles-dir", str(project), "--project-dir", str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_dbt() -> None:
    if shutil.which("dbt") is None:
        pytest.skip("dbt CLI not on PATH")


# ---------------------------------------------------------------------------
# IR-level audits (no dbt invocation -- pure planner)
# ---------------------------------------------------------------------------


def test_ir_classification_and_edges() -> None:
    """The IR classifies staging vs gold and wires the predicted edges; acyclic."""
    reg = NodeRegistry(_load_umfs())
    assert reg.staging_tables == {"member", "claims"}
    assert reg.gold_tables == {"member_claims"}
    assert reg.plan.detect_cycle() is None

    # Edges (producer -> consumer) match the predicted model parents.
    got: dict[str, set[str]] = {}
    for edge in reg.plan.edges():
        got.setdefault(edge.consumer, set()).add(edge.producer)
    assert got["gold_member_claims"] == {"ingested_claims", "ingested_member"}
    assert got["ingested_claims"] == {"raw_claims"}
    assert got["ingested_member"] == {"raw_member"}


GOLDEN_DAG_DIR = (
    Path(__file__).parent.parent / "golden" / "dbt_dag_project" / "member_claims"
)


def test_multi_table_project_matches_golden() -> None:
    """The full generated multi-table dbt project is byte-identical to the golden."""
    actual = generate_dbt_dag_project(_load_umfs())
    expected = {
        str(p.relative_to(GOLDEN_DAG_DIR)): p.read_text()
        for p in GOLDEN_DAG_DIR.rglob("*")
        if p.is_file()
    }
    assert set(actual) == set(expected), (
        f"dbt dag project file set mismatch.\n  generated: {sorted(actual)}\n"
        f"  expected:  {sorted(expected)}"
    )
    for rel, content in actual.items():
        assert content == expected[rel], (
            f"dbt dag project golden mismatch for '{rel}'.\n"
            f"--- expected ---\n{expected[rel]}\n--- actual ---\n{content}"
        )


def test_multi_table_project_is_deterministic() -> None:
    """Regenerating the same UMF set twice yields byte-identical files."""
    first = generate_dbt_dag_project(_load_umfs())
    second = generate_dbt_dag_project(_load_umfs())
    assert first == second


def test_gold_model_refs_are_static_literals() -> None:
    """Inter-table relations in the gold model are static ref()/source() Jinja."""
    files = generate_dbt_dag_project(_load_umfs())
    gold = files["models/marts/gold_member_claims.sql"]
    assert "{{ ref('ingested_claims') }}" in gold
    assert "{{ ref('ingested_member') }}" in gold
    # Fail-closed: never a phantom external source.
    assert "source('external'" not in gold
    # A dbt model body must not carry a statement terminator.
    assert not gold.rstrip().endswith(";")


# ---------------------------------------------------------------------------
# dbt parse / compile / run + manifest edge audit
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_project() -> Path:
    """Generate + build the project once; yield the project dir for reuse."""
    _require_dbt()
    project = Path(tempfile.mkdtemp(prefix="tablespec_dbtdag_"))
    generate_dbt_dag_project(_load_umfs(), out_dir=project)
    db = project / "gold.duckdb"
    _load_raw_tables(db)

    parsed = _dbt(project, db, "parse")
    assert parsed.returncode == 0, (
        f"dbt parse failed:\n{parsed.stdout}\n{parsed.stderr}"
    )
    compiled = _dbt(project, db, "compile")
    assert compiled.returncode == 0, (
        f"dbt compile failed:\n{compiled.stdout}\n{compiled.stderr}"
    )
    run = _dbt(project, db, "run")
    assert run.returncode == 0, f"dbt run failed:\n{run.stdout}\n{run.stderr}"
    yield project
    shutil.rmtree(project, ignore_errors=True)


def test_manifest_edges_match_logical_plan(built_project: Path) -> None:
    """manifest.json model edges == the IR's predicted edges (static deps only)."""
    manifest = json.loads((built_project / "target" / "manifest.json").read_text())
    parent_map = manifest["parent_map"]

    model_parents: dict[str, set[str]] = {}
    for node, parents in parent_map.items():
        if not node.startswith("model."):
            continue
        name = node.split(".")[-1]
        model_parents[name] = {p.split(".")[-1] for p in parents}

    assert model_parents == EXPECTED_MODEL_PARENTS, (
        f"manifest model edges diverge from the logical plan.\n"
        f"  manifest: {model_parents}\n  expected: {EXPECTED_MODEL_PARENTS}"
    )

    # No phantom external sources crept into the DAG.
    for src in manifest.get("sources", {}).values():
        assert src["source_name"] != "external", (
            f"phantom external source in manifest: {src['unique_id']}"
        )


def test_structural_tests_pass(built_project: Path) -> None:
    """The generated not_null / unique structural tests pass on the fixture data."""
    db = built_project / "gold.duckdb"
    result = _dbt(
        built_project,
        db,
        "test",
        "--select",
        "test_name:not_null",
        "test_name:unique",
    )
    assert result.returncode == 0, (
        f"structural dbt tests failed:\n{result.stdout}\n{result.stderr}"
    )


def test_relationships_test_is_executed_and_non_vacuous(built_project: Path) -> None:
    """The generated FK ``relationships`` test actually RUNS and is non-vacuous.

    The fixture intentionally contains one orphan claim (member_id=99, absent from
    ``member``) to exercise the gold LEFT JOIN. The generated relationships test on
    ``gold_member_claims.member_id`` -> ``ingested_member.member_id`` must:
      * be COLLECTED and COMPILED by dbt (not silently dropped), and
      * CORRECTLY FAIL with exactly the one orphan (proving it isn't vacuous -- a
        broken test pointing at the wrong model/column would not report 1 result).
    A relationships test that always passed (e.g. self-referential) would NOT catch
    this, so this is a genuine wiring + semantics check.
    """
    db = built_project / "gold.duckdb"
    result = _dbt(built_project, db, "test", "--select", "test_name:relationships")
    # The orphan makes the FK test fail -> non-zero exit; that is the point.
    assert result.returncode != 0, (
        f"relationships test did not run or unexpectedly passed:\n{result.stdout}"
    )
    out = result.stdout.lower()
    assert "relationships_gold_member_claims" in out, (
        f"the FK relationships test was not collected:\n{result.stdout}"
    )
    # Exactly one referential violation (the single orphan member_id=99).
    assert "got 1 result" in out, (
        f"expected exactly one orphan FK violation:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Semantic equivalence: dbt gold model == literal SQLPlanGenerator temp views
# ---------------------------------------------------------------------------


def _canonical_from_db(con, table_or_view: str) -> str:
    proj = ", ".join(f'"{c}"' for c in GOLD_COLUMNS)
    records = con.execute(f"SELECT {proj} FROM {table_or_view}").fetchall()
    rows = [dict(zip(GOLD_COLUMNS, rec, strict=True)) for rec in records]
    return to_json(rows, GOLD_COLUMNS, GOLD_SCALES)


def test_gold_model_semantically_equivalent_to_literal_plan(
    built_project: Path,
) -> None:
    """The dbt gold output equals the literal temp-view plan over the same data.

    Both outputs come from ONE ``SQLPlanGenerator``; only the relation renderer
    differs (dbt ``{{ ref() }}`` vs literal name). Run the literal plan against the
    SAME ``ingested_*`` staging tables dbt produced, and compare canonical rows.
    """
    db = built_project / "gold.duckdb"

    # 1. The dbt-built gold table's canonical form.
    con = _connect(db)
    try:
        dbt_canonical = _canonical_from_db(con, "gold_member_claims")

        # 2. The literal SQLPlanGenerator plan (temp views) over the SAME staging.
        #    The dbt renderer maps each table name to ``ref('ingested_<t>')``; the
        #    literal renderer here maps the SAME names to the bare ``ingested_<t>``
        #    tables dbt built in schema ``main``. Same generator, equivalent target
        #    relations -> the comparison isolates *only* the rendering difference.
        umfs = {u.table_name: u for u in _load_umfs()}
        staging = {"member", "claims"}

        def _to_ingested(name: str) -> str:
            bare = name.split(".", 1)[1] if "." in name else name
            return f"ingested_{bare}" if bare in staging else bare

        gold_umf = umfs[GOLD_TABLE]
        literal_sql = generate_sql_plan(
            gold_umf, umfs, table_resolver=_to_ingested, mode="views"
        )
        for statement in literal_sql.split(";"):
            stmt = statement.strip()
            if not stmt:
                continue
            # Drop pure-comment fragments between statements.
            sql_lines = [
                line for line in stmt.splitlines() if not line.lstrip().startswith("--")
            ]
            if not any(line.strip() for line in sql_lines):
                continue
            con.execute(stmt)
        # The literal plan's final view is named after the gold table itself.
        literal_canonical = _canonical_from_db(con, GOLD_TABLE)
    finally:
        con.close()

    assert literal_canonical == dbt_canonical, (
        "gold model is NOT semantically equivalent to the literal temp-view plan.\n"
        f"--- dbt gold ---\n{dbt_canonical}\n--- literal plan ---\n{literal_canonical}"
    )
