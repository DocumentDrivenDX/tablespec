"""Tests for the tablespec.ingestion package (FEAT-031 SRC-01..05).

Covers reader factory dispatch, encoding normalization, the raw-header
lookup/mapping utilities merge.py consumes, and the backbone's declared-source
resolution (legacy UMFs without file_format keep comma-CSV behavior).
"""

# @covers US-040-AC3
# @covers US-042-AC1
# @covers US-042-AC2
# @covers US-042-AC3
# @covers US-042-AC4
# @covers US-050-AC2
# @covers US-050-AC3

from __future__ import annotations

import pytest

from tablespec.ingestion import (
    CsvReader,
    JdbcReader,
    SourceReader,
    build_column_lookup,
    delimited_source_records,
    get_reader,
    map_headers,
    normalize_spark_encoding,
    spark_csv_options,
)
from tablespec.models.umf import (
    UMF,
    DelimitedSource,
    JdbcSource,
    JsonSource,
    ParquetSource,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestGetReader:
    def test_delimited_dispatches_to_csv_reader(self):
        reader = get_reader(DelimitedSource())
        assert isinstance(reader, CsvReader)
        assert isinstance(reader, SourceReader)

    def test_parquet_dispatches_to_parquet_reader(self):
        reader = get_reader(ParquetSource(kind="parquet"))
        assert reader.__class__.__name__ == "ParquetReader"
        assert isinstance(reader, SourceReader)

    def test_json_dispatches_to_json_reader(self):
        reader = get_reader(
            JsonSource(
                kind="json",
                path="/data/members.jsonl",
                projection=[{"column": "member_id", "path": "memberId"}],
            )
        )
        assert reader.__class__.__name__ == "JsonReader"
        assert isinstance(reader, SourceReader)

    def test_jdbc_dispatches_to_jdbc_reader(self):
        reader = get_reader(JdbcSource(kind="jdbc", url="jdbc:x", dbtable="dbo.t"))
        assert isinstance(reader, JdbcReader)
        assert isinstance(reader, SourceReader)

    def test_unknown_kind_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown source kind"):
            get_reader(object())  # type: ignore[arg-type]


class _RecordingReader:
    """Stub for spark.read capturing the options/path CsvReader passes."""

    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def options(self, **kwargs):
        self._sink["options"] = kwargs
        return self

    def csv(self, path):
        self._sink["path"] = path
        return "df"


class _StubSpark:
    def __init__(self) -> None:
        self.calls: dict = {}

    @property
    def read(self):
        return _RecordingReader(self.calls)


class TestCsvReader:
    def test_read_uses_umf_derived_options(self):
        spark = _StubSpark()
        spec = DelimitedSource(
            delimiter=",",
            encoding="latin-1",
            header=True,
            null_value="NULL",
            path="/data/members.csv",
        )
        result = CsvReader().read(spec, spark)  # type: ignore[arg-type]
        assert result == "df"
        assert spark.calls["path"] == "/data/members.csv"
        assert spark.calls["options"] == {
            "header": True,
            "sep": ",",
            "nullValue": "NULL",
            "encoding": "ISO-8859-1",
            "inferSchema": False,
        }

    def test_read_without_path_raises(self):
        with pytest.raises(ValueError, match="path"):
            CsvReader().read(DelimitedSource(), _StubSpark())  # type: ignore[arg-type]

    def test_dump_reader_normalizes_skip_footer_and_null_escape(self, tmp_path):
        path = tmp_path / "dump.csv"
        path.write_text(
            "skip one||skip two||row_id,note,_source_file,_load_ts||"
            "d1,hello,dump.csv,2026-01-01 00:00:00||"
            "d2,\\N,dump.csv,2026-01-01 00:00:01||"
            "2||"
        )
        spec = DelimitedSource(
            delimiter=",",
            header=True,
            line_terminator="||",
            skip_rows=2,
            footer_rows=1,
            null_escape="\\N",
            path=str(path),
        )
        headers, rows = delimited_source_records(spec, path)
        assert headers == ["row_id", "note", "_source_file", "_load_ts"]
        assert rows == [
            {
                "row_id": "d1",
                "note": "hello",
                "_source_file": "dump.csv",
                "_load_ts": "2026-01-01 00:00:00",
            },
            {
                "row_id": "d2",
                "note": None,
                "_source_file": "dump.csv",
                "_load_ts": "2026-01-01 00:00:01",
            },
        ]

    def test_dump_reader_uses_normalized_records(self, tmp_path):
        path = tmp_path / "dump.csv"
        path.write_text(
            "skip one||skip two||row_id,note,_source_file,_load_ts||"
            "d1,hello,dump.csv,2026-01-01 00:00:00||"
            "d2,\\N,dump.csv,2026-01-01 00:00:01||"
            "2||"
        )
        spec = DelimitedSource(
            delimiter=",",
            header=True,
            line_terminator="||",
            skip_rows=2,
            footer_rows=1,
            null_escape="\\N",
            path=str(path),
        )

        class _Spark:
            def __init__(self) -> None:
                self.calls: dict[str, object] = {}

            def createDataFrame(self, rows, schema):  # noqa: ANN001
                self.calls["rows"] = rows
                self.calls["schema"] = schema
                return "df"

        spark = _Spark()
        result = CsvReader().read(spec, spark)  # type: ignore[arg-type]
        assert result == "df"
        assert spark.calls["rows"] == [
            {
                "row_id": "d1",
                "note": "hello",
                "_source_file": "dump.csv",
                "_load_ts": "2026-01-01 00:00:00",
            },
            {
                "row_id": "d2",
                "note": None,
                "_source_file": "dump.csv",
                "_load_ts": "2026-01-01 00:00:01",
            },
        ]


class TestParquetReader:
    def test_read_uses_parquet_path(self):
        class _ParquetRead:
            def __init__(self, sink: dict[str, object]) -> None:
                self._sink = sink

            def parquet(self, path):  # noqa: ANN001
                self._sink["path"] = path
                return "df"

        class _Spark:
            def __init__(self) -> None:
                self.calls: dict[str, object] = {}

            @property
            def read(self):
                return _ParquetRead(self.calls)

        spark = _Spark()
        spec = ParquetSource(kind="parquet", path="/data/events.parquet")
        result = get_reader(spec).read(spec, spark)  # type: ignore[arg-type]
        assert result == "df"
        assert spark.calls["path"] == "/data/events.parquet"


class TestNormalizeSparkEncoding:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("latin-1", "ISO-8859-1"),
            ("latin1", "ISO-8859-1"),
            ("iso-8859-1", "ISO-8859-1"),
            ("ISO-8859-1", "ISO-8859-1"),
            ("utf8", "UTF-8"),
            ("utf-8", "UTF-8"),
            ("UTF-8", "UTF-8"),
            (" Utf-8 ", "UTF-8"),
            ("cp1252", "windows-1252"),
            ("utf-16", "UTF-16"),
            ("ascii", "US-ASCII"),
        ],
    )
    def test_aliases_normalize(self, raw, expected):
        assert normalize_spark_encoding(raw) == expected

    def test_unrecognized_value_passes_through_as_is(self):
        assert normalize_spark_encoding("koi8-r") == "koi8-r"


class TestSparkCsvOptions:
    def test_optional_characters_only_when_declared(self):
        opts = spark_csv_options(DelimitedSource())
        assert opts == {
            "header": True,
            "sep": "|",
            "encoding": "UTF-8",
            "inferSchema": False,
        }

    def test_declared_characters_included(self):
        opts = spark_csv_options(
            DelimitedSource(
                delimiter=",", null_value="NA", quote_char="'", escape_char="\\"
            )
        )
        assert opts["sep"] == ","
        assert opts["nullValue"] == "NA"
        assert opts["quote"] == "'"
        assert opts["escape"] == "\\"

    def test_comment_character_is_included(self):
        opts = spark_csv_options(DelimitedSource(comment_char="#"))
        assert opts["comment"] == "#"


def _umf() -> UMF:
    return UMF(
        version="1.0",
        table_name="members",
        columns=[
            {
                "name": "member_id",
                "data_type": "INTEGER",
                "canonical_name": "Member ID",
            },
            {
                "name": "last_name",
                "data_type": "VARCHAR",
                "length": 50,
                "aliases": ["lname", "surname"],
            },
            {
                "name": "source_vendor",
                "data_type": "VARCHAR",
                "length": 20,
                "source": "filename",
            },
        ],
    )


class TestBuildColumnLookup:
    def test_indexes_name_canonical_and_aliases_case_insensitively(self):
        lookup = build_column_lookup(_umf())
        assert lookup["member_id"].umf_column == "member_id"
        assert lookup["member id"].umf_column == "member_id"
        assert lookup["member id"].matched_via == "canonical_name"
        assert lookup["surname"].umf_column == "last_name"
        assert lookup["surname"].matched_via == "alias"

    def test_non_data_columns_excluded_by_default(self):
        lookup = build_column_lookup(_umf())
        assert "source_vendor" not in lookup

    def test_include_non_data_includes_filename_columns(self):
        lookup = build_column_lookup(_umf(), include_non_data=True)
        assert lookup["source_vendor"].umf_column == "source_vendor"

    def test_name_takes_precedence_over_alias_collision(self):
        umf = UMF(
            version="1.0",
            table_name="t",
            columns=[
                {"name": "a", "data_type": "INTEGER", "aliases": ["b"]},
                {"name": "b", "data_type": "INTEGER"},
            ],
        )
        lookup = build_column_lookup(umf)
        assert lookup["b"].umf_column == "b"
        assert lookup["b"].matched_via == "name"


class TestMapHeaders:
    def test_maps_raw_headers_to_canonical_columns(self):
        lookup = build_column_lookup(_umf())
        mapping = map_headers(["Member ID", "LNAME", "extra_col"], lookup)
        assert mapping["Member ID"].umf_column == "member_id"
        assert mapping["LNAME"].umf_column == "last_name"
        assert "extra_col" not in mapping

    def test_headers_with_surrounding_whitespace_resolve(self):
        lookup = build_column_lookup(_umf())
        mapping = map_headers(["  member_id  "], lookup)
        assert mapping["  member_id  "].umf_column == "member_id"

    def test_duplicate_targets_first_wins(self):
        lookup = build_column_lookup(_umf())
        mapping = map_headers(["last_name", "surname"], lookup)
        assert mapping["last_name"].umf_column == "last_name"
        assert "surname" not in mapping


class TestBackboneDeclaredDelimited:
    """The backbone honors declared sources and preserves legacy behavior."""

    def test_undeclared_umf_yields_none(self, tmp_path):
        from tablespec.e2e.backbone import _declared_delimited

        snap = tmp_path / "t.umf.yaml"
        snap.write_text(
            "version: '1.0'\ntable_name: t\ncolumns:\n- name: id\n  data_type: INTEGER\n"
        )
        assert _declared_delimited(snap) is None

    def test_declared_file_format_yields_delimited_spec(self, tmp_path):
        from tablespec.e2e.backbone import _declared_delimited

        snap = tmp_path / "t.umf.yaml"
        snap.write_text(
            "version: '1.0'\ntable_name: t\ncolumns:\n- name: id\n  data_type: INTEGER\n"
            "file_format:\n  delimiter: ','\n  encoding: latin-1\n"
        )
        spec = _declared_delimited(snap)
        assert isinstance(spec, DelimitedSource)
        assert spec.delimiter == ","
        assert spec.encoding == "latin-1"

    def test_declared_non_delimited_source_not_implemented(self, tmp_path):
        from tablespec.e2e.backbone import _declared_delimited

        snap = tmp_path / "t.umf.yaml"
        snap.write_text(
            "version: '1.0'\ntable_name: t\ncolumns:\n- name: id\n  data_type: INTEGER\n"
            "source:\n  kind: jdbc\n  url: jdbc:x\n  dbtable: dbo.t\n"
        )
        with pytest.raises(NotImplementedError, match="jdbc"):
            _declared_delimited(snap)

    def test_declared_json_source_is_accepted(self, tmp_path):
        """FR-21.7 residual closed: backbone parses json kind (no fail-closed)."""
        from tablespec.e2e.backbone import _declared_source
        from tablespec.models.umf import JsonSource

        snap = tmp_path / "t.umf.yaml"
        snap.write_text(
            "version: '1.0'\ntable_name: t\ncolumns:\n- name: id\n  data_type: INTEGER\n"
            "source:\n  kind: json\n  path: /data/t.jsonl\n  projection:\n"
            "  - column: id\n    path: id\n"
        )
        spec = _declared_source(snap)
        assert isinstance(spec, JsonSource)
        assert spec.kind == "json"
        assert spec.projection[0].column == "id"
