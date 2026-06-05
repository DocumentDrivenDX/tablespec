"""Phase 0 proof: the generated dbt project is VALID for a Databricks target offline.

dbt-databricks is COMPILE-ONLY in this environment (no cluster). IMPORTANT nuance,
verified in this env: ``dbt compile`` for the databricks adapter is NOT offline --
it opens a SQL-warehouse connection to populate the relation cache and retries
~30x with backoff against an unreachable host (it hangs, it does not "compile
without a cluster"). The genuinely offline, no-cluster validation is ``dbt parse``:
it builds the full manifest, registers the databricks adapter, and renders every
node's ``{{ ref()/source() }}`` + Jinja WITHOUT connecting. That proves the project
is well-formed for Databricks.

To also prove the Databricks-dialect SQL itself (the cast a Databricks cluster
would execute), the test asserts the emitted model body carries the Spark-form
``try_to_timestamp`` cast -- Databricks SQL == Spark SQL for our casts, so the
``databricks`` dialect renders identically to ``spark`` (this is the contract that
lets the executed Spark leg stand in for the Databricks runtime).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.slow]

pytest.importorskip(
    "dbt.adapters.databricks",
    reason="dbt-databricks required for the compile-only Databricks tier",
)

from tablespec.schemas.dbt_generator import generate_dbt_project  # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ingest"

_FIXTURE = "events_incremental_nopk"
# Databricks SQL == Spark SQL for our casts: the databricks dialect must emit the
# identical Java-token try_to_timestamp a Databricks cluster would execute.
_EXPECTED_CAST = "try_to_timestamp(occurred_at, 'yyyy-MM-dd HH:mm:ss')"


def test_dbt_databricks_parses_without_cluster() -> None:
    """`dbt parse` validates the databricks-target project fully offline (no cluster)."""
    from dbt.cli.main import dbtRunner

    umf = yaml.safe_load((FIXTURE_DIR / f"{_FIXTURE}.umf.yaml").read_text())

    work = Path(tempfile.mkdtemp(prefix=f"conformance_databricks_{_FIXTURE}_"))
    try:
        project = work / "proj"
        project.mkdir()
        files = generate_dbt_project(
            umf, dialect="databricks", target="databricks", out_dir=project
        )

        # The emitted profile selects the databricks adapter, and the model body
        # carries the Databricks==Spark cast (asserted on the source text, which is
        # what a Databricks cluster would run).
        assert "type: databricks" in files["profiles.yml"]
        assert _EXPECTED_CAST in files[f"models/{umf['table_name']}.sql"]

        # parse = offline manifest build + render under the databricks adapter.
        result = dbtRunner().invoke(
            [
                "parse",
                "--profiles-dir",
                str(project),
                "--project-dir",
                str(project),
                "--target",
                "dev",
                "--no-partial-parse",
            ]
        )
        assert result.success, (
            "dbt parse failed for the databricks target (project not well-formed "
            "for Databricks)."
        )

        # Inspect the manifest dbt actually built: prove the node was parsed under
        # the DATABRICKS adapter and that the rendered model body carries the
        # Spark-form cast (not just the pre-parse source file). The manifest's
        # raw_code is the post-Jinja-aware node dbt would dispatch to Databricks.
        manifest = json.loads((project / "target" / "manifest.json").read_text())
        assert manifest["metadata"]["adapter_type"] == "databricks", (
            f"manifest not parsed under databricks adapter: "
            f"{manifest['metadata']['adapter_type']!r}"
        )
        node = manifest["nodes"][f"model.tablespec_ingest.{umf['table_name']}"]
        assert _EXPECTED_CAST in node["raw_code"], (
            "the databricks-parsed model node does not carry the try_to_timestamp "
            "cast a Databricks cluster would execute"
        )
        # The model's materialization config survived parsing for the databricks target.
        assert node["config"]["materialized"] == "incremental"
    finally:
        shutil.rmtree(work, ignore_errors=True)
