# Databricks notebook source
# MAGIC %md
# MAGIC # Load the mixed legal pack
# MAGIC Import this source file as a Databricks notebook. Install the TableSpec wheel
# MAGIC built from this change with `%pip install /Volumes/.../tablespec-....whl`,
# MAGIC then restart Python if requested. Use the runtime Spark session.
# MAGIC Set `pack_path` to the checked-out `examples/domain-packs/legal/domain-pack.json`.
# MAGIC The pack's adjacent schemas, CSV files and PDFs must be present.
# MAGIC Use a dedicated catalog/schema: loading replaces these eleven target tables.
# MAGIC `local-use` retains uncleared third-party rights and does not clear redistribution.

# COMMAND ----------

# COMMAND ----------

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import shutil

from tablespec.sample_data.mixed import MixedDataset
from tablespec.sample_data.sink import SparkSQLSink, load_dataset, target_namespace
from tablespec.sample_data.verification import verify_loaded
from tablespec.spark_factory import create_delta_spark_session

dbutils = globals()["dbutils"]
dbutils.widgets.text("pack_path", "")
dbutils.widgets.text("target", "")
dbutils.widgets.dropdown("scale", "small", ["small", "demo", "large"])
dbutils.widgets.text("seed", "42")
dbutils.widgets.text("originals_volume", "")
dbutils.widgets.dropdown("load_tables", "false", ["false", "true"])


# COMMAND ----------

pack_path = Path(dbutils.widgets.get("pack_path"))
target = dbutils.widgets.get("target")
if not target or not pack_path.is_file():
    raise ValueError(
        "Set pack_path to the complete local pack and target to catalog.schema"
    )
target_namespace(target)
scale = dbutils.widgets.get("scale")
seed = int(dbutils.widgets.get("seed"))
volume = dbutils.widgets.get("originals_volume")
write_tables = dbutils.widgets.get("load_tables") == "true"
if volume and (not volume.startswith("/Volumes/") or ".." in Path(volume).parts):
    raise ValueError("originals_volume must be a Unity Catalog Volume subdirectory")

# COMMAND ----------

# Preflight is the default: no workspace data writes until load_tables=true.
# Source hashing, type/FK checks and generated relational audits finish first.
with TemporaryDirectory(prefix="legal-mixed-") as temp:
    data = MixedDataset(Path(temp) / "rows.sqlite", pack_path, scale, seed, "local-use")
    try:
        print(json.dumps({"counts": data.counts, "run": data.run_metadata}, indent=2))
        if write_tables:
            sink = SparkSQLSink(create_delta_spark_session("mixed-legal-import"))
            load_dataset(data, target, sink)
            result = verify_loaded(data.specs, data.counts, target, sink, legal=True)
            # Check representative real multiline text after the native write.
            from tablespec.sample_data.sink import literal

            expected = next(data.batches("evidence_pages"))[0]
            actual = sink.query(
                f"SELECT text FROM {target}.evidence_pages WHERE page_key={literal(expected['page_key'])}"
            )
            if actual != [[expected["text"]]]:
                raise RuntimeError("Evidence text readback differs")
            print(json.dumps(result, indent=2))
            if volume:
                destination = Path(volume)
                if (
                    not str(destination).startswith("/Volumes/")
                    or ".." in destination.parts
                ):
                    raise ValueError(
                        "originals_volume must be a Unity Catalog Volume subdirectory"
                    )
                destination.mkdir(parents=True, exist_ok=True)
                originals = {}
                for source_id, source in data.source_metadata["sources"].items():
                    if source.get("format") != "pdf":
                        continue
                    source_file = data.source_artifacts[source["reference"]]
                    output = destination / source_file.name
                    if (
                        output.exists()
                        and hashlib.sha256(output.read_bytes()).hexdigest()
                        != source["checksum"]["value"]
                    ):
                        raise ValueError(
                            "Existing Volume original differs; choose a fresh subdirectory"
                        )
                    shutil.copyfile(source_file, output)
                    if (
                        hashlib.sha256(output.read_bytes()).hexdigest()
                        != source["checksum"]["value"]
                    ):
                        raise RuntimeError("Volume original checksum differs")
                    originals[source_id] = {
                        "path": str(output),
                        "sha256": source["checksum"]["value"],
                        "redistribution": source["license"]["redistribution"],
                    }
                (destination / "legal-source-map.json").write_text(
                    json.dumps(
                        {
                            "source_policy": "local-use",
                            "pack_sha256": data.run_metadata["pack_sha256"],
                            "originals": originals,
                        },
                        indent=2,
                    )
                )
                print(
                    "Seven original PDFs copied and hash verified in the configured Volume"
                )
            print("Mixed legal load verification PASSED")
        else:
            print("Preflight PASSED. Set load_tables=true to load the reviewed target.")
    finally:
        data.close()
