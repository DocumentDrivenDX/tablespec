"""Execute generated Delta DDL and inserts on local Sail and classic Spark.

Sail command results carry unsigned counts; use Arrow directly rather than
PySpark Row conversion. DDL and row writes execute unchanged; Sail comment-refresh commands are recorded
separately because that engine does not implement them.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from hypothesis import example, given, settings, strategies as st
import pytest

from tablespec.sample_data.sink import delta_ddl, literal, load_dataset
from tablespec.sample_data.verification import verify_loaded
from tests.unit.test_legal_sample_data import dataset

pytestmark = pytest.mark.no_spark


class ArrowSink:
    def __init__(self, spark, backend):
        self.spark = spark
        self.backend = backend
        self.comment_refreshes = []

    def execute(self, statement):
        # Sail 0.6.6 supports inline DDL comments, but not comment refresh
        # commands. The Spark leg executes those commands; this test port
        # records them to keep the Sail ingestion claim explicitly bounded.
        if self.backend == "sail" and statement.startswith(
            ("COMMENT ON TABLE", "ALTER TABLE")
        ):
            self.comment_refreshes.append(statement)
            return
        frame = self.spark.sql(statement)
        if self.backend == "spark":
            frame._jdf.collect()  # JVM-only command results; no Python socket collector.
        else:
            frame.toArrow()

    def query(self, statement):
        frame = self.spark.sql(statement)
        if self.backend == "spark":
            result = []
            for row in frame._jdf.collect():
                values = []
                for index, field in enumerate(frame.schema.fields):
                    value = row.get(index)
                    if value is not None and field.dataType.typeName() == "date":
                        value = date.fromisoformat(str(value))
                    elif value is not None and field.dataType.typeName() == "timestamp":
                        value = datetime.fromisoformat(str(value.toInstant()))
                    if value is not None and field.dataType.typeName() == "decimal":
                        value = Decimal(str(value))
                    values.append(value)
                result.append(values)
            return result
        table = frame.toArrow()
        return [
            list(row)
            for row in zip(
                *(column.to_pylist() for column in table.columns), strict=True
            )
        ]


@pytest.fixture(scope="module", params=["sail", "spark"])
def ingestion_sink(request, tmp_path_factory):
    server = None
    if request.param == "sail":
        from pysail.spark import SparkConnectServer
        from pyspark.sql.connect.session import SparkSession

        server = SparkConnectServer()
        server.start()
        host, port = server.listening_address
        spark = SparkSession.builder.remote(f"sc://{host}:{port}").create()
    else:
        spark = request.getfixturevalue("spark_session")
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    warehouse = tmp_path_factory.mktemp("sample-warehouse")
    if request.param == "sail":
        spark.conf.set("spark.sql.warehouse.dir", str(warehouse))
    sink = ArrowSink(spark, request.param)
    namespace = "spark_catalog.sample_test_" + uuid4().hex
    sink.execute(f"CREATE SCHEMA {namespace} LOCATION {literal(str(warehouse))}")
    try:
        yield sink, namespace
    finally:
        try:
            sink.execute(f"DROP SCHEMA {namespace} CASCADE")
        finally:
            if server:
                spark.stop()
                server.stop()


def test_small_legal_load_readback_and_replacement(ingestion_sink, tmp_path: Path):
    sink, target = ingestion_sink
    data = dataset(tmp_path)
    try:
        for _ in range(2):
            load_dataset(data, target, sink, batch_size=17)
            verify_loaded(data.specs, data.counts, target, sink, True)
    finally:
        data.close()


@given(
    value=st.text(
        alphabet=st.sampled_from(["a", "'", "\\", "\n", "\t", "\x00", "😀"]),
        max_size=50,
    )
)
@example(value="trailing\\")
@example(value="quote' slash\\ newline\n tab\t NUL\0 emoji😀")
@settings(max_examples=20, deadline=None)
def test_awkward_string_roundtrip(ingestion_sink, value):
    sink, target = ingestion_sink
    table = target + ".literal_probe"
    spec = {
        "table_name": "literal_probe",
        "columns": [{"name": "value", "data_type": "STRING"}],
    }
    sink.execute(
        delta_ddl(spec, table).replace(
            "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1
        )
    )
    sink.execute(f"INSERT OVERWRITE {table} VALUES ({literal(value)})")
    assert sink.query(f"SELECT value FROM {table}") == [[value]]


def test_date_and_timestamp_ddl_accept_typed_values(ingestion_sink):
    sink, target = ingestion_sink
    table = target + ".temporal_probe"
    spec = {
        "table_name": "temporal_probe",
        "columns": [
            {"name": "day", "data_type": "DATE"},
            {"name": "moment", "data_type": "TIMESTAMP"},
        ],
    }
    sink.execute(delta_ddl(spec, table))
    day, moment = date(2026, 10, 8), datetime(2026, 10, 8, 12, 30)
    sink.execute(
        f"INSERT INTO {table} VALUES ({literal(day, 'DATE')},{literal(moment, 'TIMESTAMP')})"
    )
    actual = sink.query(f"SELECT day,moment FROM {table}")[0]
    assert actual[0] == day
    assert actual[1].replace(tzinfo=None) == moment


def test_csv_zip_ingestion_and_readback(ingestion_sink, tmp_path):
    from zipfile import ZipFile
    from tablespec.sample_data.archive import export_csv_zip

    sink, namespace = ingestion_sink
    data = dataset(tmp_path)
    archive_path = tmp_path / "legal.zip"
    csv_dir = tmp_path / "unpacked"
    target = namespace + "_csv"
    sink.execute(
        f"CREATE SCHEMA {target} LOCATION {literal(str(tmp_path / 'csv-warehouse'))}"
    )
    try:
        export_csv_zip(data, archive_path)
        with ZipFile(archive_path) as archive:
            archive.extractall(csv_dir)
        for name, spec in data.specs.items():
            table = f"{target}.{name}"
            sink.execute(delta_ddl(spec, table))
            # The pack reader preserves empty strings explicitly. Sail's native
            # CSV reader currently collapses quoted empties into NULL.
            from tablespec.sample_data.archive import read_csv_rows

            rows = list(read_csv_rows(csv_dir / "data" / f"{name}.csv", spec))
            schema = sink.spark.table(table).schema
            frame = sink.spark.createDataFrame(
                [tuple(row[c.name] for c in schema.fields) for row in rows], schema
            )
            frame.write.mode("overwrite").insertInto(table)
        verify_loaded(data.specs, data.counts, target, sink, True)
    finally:
        try:
            sink.execute(f"DROP SCHEMA {target} CASCADE")
        finally:
            data.close()


def test_official_medical_csv_load_readback_and_replacement(ingestion_sink, tmp_path):
    from tablespec.sample_data.ingest import ImportedDataset
    from tests.unit.test_medical_sample_data import EXAMPLE

    sink, target = ingestion_sink
    data = ImportedDataset(tmp_path / "medical.sqlite", EXAMPLE / "domain-pack.json")
    try:
        expected = {
            row["resource_key"]: row["resource_json"]
            for batch in data.batches("resources")
            for row in batch
        }
        for _ in range(2):
            load_dataset(data, target, sink, batch_size=3)
            verify_loaded(data.specs, data.counts, target, sink)
            assert (
                dict(
                    sink.query(
                        f"SELECT resource_key,resource_json FROM {target}.resources"
                    )
                )
                == expected
            )
            assert sink.query(
                f"SELECT value_decimal,effective_start FROM {target}.observations WHERE resource_key='Observation/body-height'"
            ) == [["66.899999999999991", "1999-07-02"]]
    finally:
        data.close()


@pytest.mark.parametrize(
    "pack_name",
    [
        "commerce",
        "supply-chain",
        "cybersecurity",
        "manufacturing",
        "payments",
        "education",
        "transit",
        "real-estate",
        "energy",
        "hr",
        "martech",
        "construction",
        "ecology",
        "archaeology",
    ],
)
def test_domain_catalog_native_queries_and_replacement(
    ingestion_sink, tmp_path, pack_name
):
    """Native engine subset, independent domain questions and repeated replacement.
    @covers US-063-AC6 @covers US-064-AC6 @covers US-065-AC6 @covers US-066-AC6
    @covers US-067-AC6 @covers US-068-AC6 @covers US-069-AC6 @covers US-070-AC6
    @covers US-071-AC6 @covers US-072-AC6 @covers US-073-AC6 @covers US-074-AC6
    @covers US-075-AC6 @covers US-076-AC6
    """
    import json
    import re
    from decimal import Decimal
    from tablespec.sample_data.ingest import ImportedDataset

    root = Path(__file__).parents[2]
    reviewed = json.loads(
        (root / "tests/fixtures/domain-packs/reviewed-checks.json").read_text()
    )[pack_name]
    data = ImportedDataset(
        tmp_path / "catalog.sqlite",
        root / "examples/domain-packs" / pack_name / "domain-pack.json",
    )
    sink, namespace = ingestion_sink
    target = namespace + "_" + pack_name.replace("-", "_")
    try:
        sink.execute(f"CREATE SCHEMA {target}")
        for _ in range(2):
            load_dataset(data, target, sink, batch_size=17)
            verify_loaded(data.specs, data.counts, target, sink, False)
        assert data.source_metadata["scenario_checks"] == reviewed["checks"]
        for check in reviewed["checks"]:
            query = re.sub(
                r"\b("
                + "|".join(
                    re.escape(n) for n in sorted(data.specs, key=len, reverse=True)
                )
                + r")\b",
                lambda m: target + "." + m.group(0),
                check["sql"],
            )

            def normalized(value):
                if isinstance(value, (float, Decimal)):
                    return Decimal(str(value))
                return value

            actual = [[normalized(value) for value in row] for row in sink.query(query)]
            expected = [
                [normalized(value) for value in row] for row in check["expected"]
            ]
            assert actual == expected, check["id"]
        for name, spec in data.specs.items():
            columns = [c["name"] for c in spec["columns"]]
            actual = sink.query(
                f"SELECT {','.join(columns)} FROM {target}.{name} ORDER BY id"
            )
            expected = [
                [row[c] for c in columns]
                for batch in data.batches(name)
                for row in batch
            ]
            expected.sort(key=lambda row: row[0])
            assert actual == expected, name
    finally:
        data.close()
        sink.execute(f"DROP SCHEMA {target} CASCADE")
