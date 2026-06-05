"""Phase 0 proof: the dbt project EXECUTES on a local Spark session (not skipped).

This is the executed dbt-on-Spark leg of the conformance harness. It generates a
dbt project for an existing ingest fixture with the ``spark`` (``method: session``)
profile, runs ``dbt run`` IN-PROCESS on a local Delta Spark session (isolated
warehouse + Derby metastore), reads the resulting model table back, and asserts:

  * dbt actually RAN the model (``result.success`` and node status ``success``) --
    a skip would fail the test, not pass it silently;
  * the casts executed: the ``try_to_timestamp`` date cast produced a real
    ``timestamp`` column (a malformed value -> NULL), and the numeric/decimal casts
    ran; and
  * the canonicalized output is BYTE-IDENTICAL to the committed Spark-direct oracle
    golden under ``tests/golden/ingest_parity/`` -- i.e. the dbt-on-Spark path
    reproduces the previous (Spark-direct) implementation exactly.

The ``events`` fixture is used because it is all-nullable (so contract enforcement
needs no ``SET NOT NULL`` gymnastics) yet still exercises the format-aware
``try_to_timestamp`` cast and a currency-stripping DECIMAL cast.

Run with::

    UV_PROJECT_ENVIRONMENT=/tmp/tsvenv JAVA_HOME=.../openjdk@17 SPARK_LOCAL_IP=127.0.0.1 \
      uv run pytest tests/conformance/test_dbt_spark_executed.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

# dbt-spark's thrift/session connection objects are closed lazily by the GC, so a
# ResourceWarning for an unclosed socket can surface during teardown and pytest's
# unraisableexception plugin re-raises it (the suite runs filterwarnings=error).
# That socket lifecycle is dbt-spark's, not the behaviour under test, so it is
# ignored here -- the cast/materialisation correctness is asserted explicitly.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

pytest.importorskip("pyspark", reason="pyspark required for the dbt-on-spark leg")
pytest.importorskip(
    "dbt.adapters.spark", reason="dbt-spark required (the executed leg)"
)

from tablespec.schemas.dbt_generator import generate_dbt_project  # noqa: E402

from tests.conformance._spark_dbt import (  # noqa: E402
    load_raw_table,
    make_isolated_delta_session,
    run_dbt_in_process,
)
from tests.ingest_parity.canonical import to_json  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ingest"
GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "ingest_parity"

# All-nullable fixture: still exercises try_to_timestamp + currency DECIMAL casts,
# but avoids the dbt-spark contract SET-NOT-NULL friction on a managed table.
_FIXTURE = "events_incremental_nopk"


def _decimal_scales(umf: dict[str, Any]) -> dict[str, int | None]:
    scales: dict[str, int | None] = {}
    for col in umf["columns"]:
        if (col.get("data_type") or "").upper() == "DECIMAL":
            scales[col["name"]] = col["scale"] if col.get("scale") is not None else 2
    return scales


def test_dbt_runs_on_local_spark_session() -> None:
    """dbt materializes the model on a local Spark session and matches the oracle."""
    umf = yaml.safe_load((FIXTURE_DIR / f"{_FIXTURE}.umf.yaml").read_text())
    table = umf["table_name"]
    columns = [c["name"] for c in umf["columns"]]

    work = Path(tempfile.mkdtemp(prefix=f"conformance_spark_{_FIXTURE}_"))
    spark = None
    try:
        project = work / "proj"
        project.mkdir()
        # Spark dialect cast SQL + spark(session) profile target.
        generate_dbt_project(umf, dialect="spark", target="spark", out_dir=project)

        spark = make_isolated_delta_session("conformance-spark-executed", work)

        # The events fixture is two-batch (keyless incremental = blind append).
        batches = [
            FIXTURE_DIR / f"{_FIXTURE}.batch1.csv",
            FIXTURE_DIR / f"{_FIXTURE}.batch2.csv",
        ]
        for batch in batches:
            assert batch.exists(), f"missing raw batch: {batch}"
            load_raw_table(spark, umf, batch)
            result = run_dbt_in_process(project, schema="default")
            # PROVE it executed (not skipped): success + node ran.
            assert result.success, (
                "dbt run did NOT succeed on the local Spark session:\n"
                + "\n".join(
                    f"{r.node.name}: {r.status} -- {getattr(r, 'message', '')}"
                    for r in (result.result or [])
                )
            )
            statuses = {r.node.name: str(r.status) for r in (result.result or [])}
            assert statuses == {table: "success"}, (
                f"expected the {table} model to RUN with status success, got {statuses}"
            )

        out = spark.table(f"default.{table}")
        # The format-aware cast genuinely ran -> a real timestamp column.
        assert dict(out.dtypes)["occurred_at"] == "timestamp"

        rows = [r.asDict() for r in out.collect()]
        actual = to_json(rows, columns, _decimal_scales(umf))
    finally:
        if spark is not None:
            spark.stop()
        shutil.rmtree(work, ignore_errors=True)

    golden = GOLDEN_DIR / f"{_FIXTURE}.spark.expected.json"
    assert golden.exists(), f"Spark oracle golden missing: {golden}"
    expected = golden.read_text()
    assert actual == expected, (
        f"dbt-on-Spark output for '{_FIXTURE}' must match the Spark-direct oracle.\n"
        f"--- expected (spark oracle) ---\n{expected}\n--- actual (dbt/spark) ---\n{actual}"
    )
