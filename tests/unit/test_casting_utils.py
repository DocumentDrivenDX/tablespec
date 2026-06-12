"""Tests for casting_utils module - pure Python parts only.

PySpark-dependent functions are tested by checking they raise ImportError
when PySpark is unavailable, or skipped if PySpark is present.
"""

from __future__ import annotations

import pytest

from tablespec.casting_utils import (
    COMMON_DATE_FORMATS,
    COMMON_TIMESTAMP_FORMATS,
    EPOCH_MS_FORMAT,
    EXCEL_SERIAL_FORMAT,
    build_flexible_formats,
    cast_column_sql,
    convert_umf_format_to_duckdb,
    convert_umf_format_to_spark,
)
from tablespec.date_formats import SUPPORTED_DATE_FORMATS

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestCastColumnSql:
    """Pure-Python SQL cast expression generation (no PySpark)."""

    def test_string_types_passthrough(self):
        """String-family types are already strings -- no cast emitted."""
        for t in ("VARCHAR", "TEXT", "CHAR", "STRING"):
            assert cast_column_sql("col", t) == "col"

    def test_integer_cleans_and_casts(self):
        """INTEGER strips currency/empties then casts to INT."""
        assert (
            cast_column_sql("age", "INTEGER")
            == "cast(nullif(trim(regexp_replace(age, '^\\\\$', '')), '') as INT)"
        )

    def test_decimal_uses_precision_and_scale(self):
        """DECIMAL honours precision/scale so the cast matches the typed column."""
        assert (
            cast_column_sql("amt", "DECIMAL", precision=18, scale=2)
            == "cast(nullif(trim(regexp_replace(amt, '^\\\\$', '')), '') as DECIMAL(18,2))"
        )

    def test_decimal_defaults_to_10_2(self):
        """DECIMAL without precision/scale defaults to (10,2), matching the runtime caster."""
        assert "DECIMAL(10,2)" in cast_column_sql("amt", "DECIMAL")

    def test_float_maps_to_double(self):
        """FLOAT casts to DOUBLE (runtime maps FLOAT to DoubleType)."""
        assert cast_column_sql("rate", "FLOAT").endswith("as DOUBLE)")

    def test_date_with_format(self):
        """DATE with a UMF format uses try_to_timestamp + cast to date."""
        assert (
            cast_column_sql("d", "DATE", "YYYYMMDD")
            == "cast(try_to_timestamp(d, 'yyyyMMdd') as date)"
        )

    def test_timestamp_with_format(self):
        """TIMESTAMP keeps the full timestamp; format is converted to Spark tokens."""
        assert (
            cast_column_sql("ts", "TIMESTAMP", "YYYY-MM-DD HH:MM:SS")
            == "try_to_timestamp(ts, 'yyyy-MM-dd HH:mm:ss')"
        )

    def test_datetime_treated_as_timestamp(self):
        """UMF DATETIME maps to TIMESTAMP (no date truncation)."""
        assert (
            cast_column_sql("ts", "DATETIME", "YYYY-MM-DD")
            == "try_to_timestamp(ts, 'yyyy-MM-dd')"
        )

    def test_date_without_format(self):
        """DATE with no format still parses gracefully via try_to_timestamp."""
        assert cast_column_sql("d", "DATE") == "cast(try_to_timestamp(d) as date)"

    @pytest.mark.parametrize(
        ("dialect", "expected"),
        [("spark", "cast(d as date)"), ("duckdb", "try_cast(d as date)")],
    )
    def test_typed_raw_date_uses_safe_cast(self, dialect, expected):
        """Typed raw DATE values stay typed and never route through string parsing."""
        expr = cast_column_sql(
            "d",
            "DATE",
            "YYYY-MM-DD",
            dialect=dialect,
            source_kind="parquet",
        )
        assert expr == expected
        assert "try_to_timestamp" not in expr
        assert "try_strptime" not in expr

    @pytest.mark.parametrize(
        ("dialect", "expected"),
        [
            ("spark", "cast(ts as timestamp)"),
            ("duckdb", "try_cast(ts as timestamp)"),
        ],
    )
    def test_typed_raw_timestamp_uses_safe_cast(self, dialect, expected):
        expr = cast_column_sql(
            "ts",
            "TIMESTAMP",
            "YYYY-MM-DD HH:MM:SS",
            dialect=dialect,
            source_kind="jdbc",
        )
        assert expr == expected
        assert "try_to_timestamp" not in expr
        assert "try_strptime" not in expr

    def test_boolean(self):
        """BOOLEAN is a plain cast."""
        assert cast_column_sql("flag", "BOOLEAN") == "cast(flag as boolean)"

    def test_unsupported_type_raises(self):
        """Unknown target types raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported target_type"):
            cast_column_sql("col", "GEOGRAPHY")

    def test_unsupported_dialect_raises(self):
        """An unknown dialect raises ValueError."""
        with pytest.raises(
            ValueError,
            match=r"Unsupported dialect: 'postgres' \(expected one of spark, databricks, duckdb\)",
        ):
            cast_column_sql("col", "INTEGER", dialect="postgres")

    @pytest.mark.parametrize("dialect", ["spark", "duckdb"])
    @pytest.mark.parametrize("fmt", ["MM/DD/YY", "M/D/YY", "YY-MM-DD"])
    def test_two_digit_year_rejected_symmetrically(self, dialect, fmt):
        """2-digit-year formats raise in BOTH dialects (no silent century divergence).

        Spark's ``yy`` always resolves to 20xx, DuckDB's ``%y`` pivots at 1969, so a
        2-digit year is intentionally NOT in the shared registry; both ingest
        emitters reject it identically rather than producing divergent output.
        """
        with pytest.raises(ValueError, match="cross-engine ingest"):
            cast_column_sql("d", "DATE", fmt, dialect=dialect)

    @pytest.mark.parametrize("dialect", ["spark", "duckdb"])
    def test_unregistered_date_format_rejected(self, dialect):
        """A date format outside the shared registry is rejected in both dialects."""
        with pytest.raises(ValueError, match="cross-engine ingest"):
            cast_column_sql("d", "DATE", "DD.MM.YYYY", dialect=dialect)


class TestCastColumnSqlDuckdb:
    """DuckDB-dialect SQL cast expression generation (no PySpark)."""

    def test_string_types_passthrough_identical(self):
        """String-family types pass through identically in both dialects."""
        for t in ("VARCHAR", "TEXT", "CHAR", "STRING"):
            assert cast_column_sql("col", t, dialect="duckdb") == "col"

    def test_integer_uses_try_cast_and_single_backslash(self):
        """INTEGER uses try_cast and a single-backslash currency strip for DuckDB."""
        assert (
            cast_column_sql("age", "INTEGER", dialect="duckdb")
            == "try_cast(nullif(trim(regexp_replace(age, '^\\$', '')), '') as INT)"
        )

    def test_decimal_uses_precision_and_scale(self):
        """DECIMAL honours precision/scale under try_cast."""
        assert (
            cast_column_sql("amt", "DECIMAL", precision=18, scale=2, dialect="duckdb")
            == "try_cast(nullif(trim(regexp_replace(amt, '^\\$', '')), '') "
            "as DECIMAL(18,2))"
        )

    def test_float_maps_to_double(self):
        """FLOAT casts to DOUBLE under try_cast."""
        assert cast_column_sql("rate", "FLOAT", dialect="duckdb").endswith("as DOUBLE)")

    def test_date_with_format_uses_try_strptime(self):
        """DATE uses try_strptime with strftime codes, gated by a padding regex.

        The ``regexp_full_match`` guard reproduces Spark's zero-padding strictness
        so a malformed-padding value Spark would NULL also NULLs in DuckDB.
        """
        assert (
            cast_column_sql("d", "DATE", "YYYYMMDD", dialect="duckdb")
            == "cast(case when regexp_full_match(d, '\\d{4}\\d{2}\\d{2}') "
            "then try_strptime(d, '%Y%m%d') end as date)"
        )

    def test_timestamp_with_format_uses_try_strptime(self):
        """TIMESTAMP keeps the full timestamp via try_strptime, padding-gated."""
        assert (
            cast_column_sql("ts", "TIMESTAMP", "YYYY-MM-DD HH:MM:SS", dialect="duckdb")
            == "case when regexp_full_match(ts, '\\d{4}\\-\\d{2}\\-\\d{2}\\ "
            "\\d{2}:\\d{2}:\\d{2}') then try_strptime(ts, '%Y-%m-%d %H:%M:%S') end"
        )

    def test_padded_date_format_rejects_unpadded_input(self):
        """The duckdb padding regex demands the exact field widths Spark requires."""
        from tablespec.casting_utils import _duckdb_padding_prefilter_regex

        assert _duckdb_padding_prefilter_regex("%m/%d/%Y") == r"\d{2}/\d{2}/\d{4}"
        # non-padding directives accept one or two digits (Spark M/d leniency)
        assert _duckdb_padding_prefilter_regex("%-m/%-d/%Y") == r"\d{1,2}/\d{1,2}/\d{4}"
        # fractional seconds: %f defaults to 1-6 digits, but the cap is overridable
        # so the millisecond (.SSS) format narrows to 1-3 (matching Spark).
        assert (
            _duckdb_padding_prefilter_regex("%H:%M:%S.%f")
            == r"\d{2}:\d{2}:\d{2}\.\d{1,6}"
        )
        assert (
            _duckdb_padding_prefilter_regex("%H:%M:%S.%f", fractional_cap=3)
            == r"\d{2}:\d{2}:\d{2}\.\d{1,3}"
        )
        # AM/PM marker is case-insensitive (Spark + DuckDB both accept "Pm"); the
        # space between %M and %p is escaped by re.escape.
        assert _duckdb_padding_prefilter_regex("%I:%M %p") == r"\d{2}:\d{2}\ [AaPp][Mm]"

    def test_fractional_digit_cap_from_umf_s_run(self):
        """The fractional cap is the length of the UMF ``.S`` run."""
        from tablespec.casting_utils import _fractional_digit_cap

        assert _fractional_digit_cap("YYYY-MM-DD HH:MM:SS.SSS") == 3
        assert _fractional_digit_cap("YYYY-MM-DD HH:MM:SS.SSSSSS") == 6
        assert _fractional_digit_cap("YYYY-MM-DD HH:MM:SS") == 6  # no fraction
        assert _fractional_digit_cap(None) == 6

    def test_date_without_format_uses_try_cast(self):
        """DATE without a format casts through DuckDB's TIMESTAMP parser."""
        assert (
            cast_column_sql("d", "DATE", dialect="duckdb")
            == "cast(try_cast(d as timestamp) as date)"
        )

    def test_boolean_uses_try_cast(self):
        """BOOLEAN uses try_cast for NULL-on-failure parity with Spark."""
        assert (
            cast_column_sql("flag", "BOOLEAN", dialect="duckdb")
            == "try_cast(flag as boolean)"
        )

    def test_double_type_maps_to_double(self):
        """A DOUBLE column casts to DOUBLE under try_cast (duckdb)."""
        assert (
            cast_column_sql("rate", "DOUBLE", dialect="duckdb")
            == "try_cast(nullif(trim(regexp_replace(rate, '^\\$', '')), '') as DOUBLE)"
        )

    def test_timestamp_without_format_uses_try_cast(self):
        """TIMESTAMP without a format casts through DuckDB's permissive parser."""
        assert (
            cast_column_sql("ts", "TIMESTAMP", dialect="duckdb")
            == "try_cast(ts as timestamp)"
        )


class TestCastColumnSqlSparkDialectExtras:
    """Spark-dialect SQL cast branches not covered elsewhere (no PySpark)."""

    def test_double_type_maps_to_double(self):
        assert (
            cast_column_sql("rate", "DOUBLE")
            == "cast(nullif(trim(regexp_replace(rate, '^\\\\$', '')), '') as DOUBLE)"
        )

    def test_timestamp_without_format(self):
        assert cast_column_sql("ts", "TIMESTAMP") == "try_to_timestamp(ts)"


class TestCastColumnSqlDatabricksAlias:
    @pytest.mark.parametrize(
        ("target_type", "fmt", "kwargs"),
        [
            ("INTEGER", None, {}),
            ("DECIMAL", None, {"precision": 18, "scale": 2}),
            ("DATE", "YYYY-MM-DD", {}),
            ("TIMESTAMP", None, {}),
            ("BOOLEAN", None, {}),
            ("DATE", EPOCH_MS_FORMAT, {}),
            ("TIMESTAMP", EPOCH_MS_FORMAT, {}),
            ("DATE", EXCEL_SERIAL_FORMAT, {}),
        ],
    )
    def test_databricks_alias_matches_spark(self, target_type, fmt, kwargs):
        spark_sql = cast_column_sql("c", target_type, fmt, dialect="spark", **kwargs)
        databricks_sql = cast_column_sql(
            "c", target_type, fmt, dialect="databricks", **kwargs
        )
        assert databricks_sql == spark_sql


class TestConvertUmfFormatToDuckdb:
    """UMF format -> DuckDB strptime %-code conversion (registry-driven)."""

    def test_iso_date(self):
        assert convert_umf_format_to_duckdb("YYYY-MM-DD") == "%Y-%m-%d"

    def test_us_date_slashes(self):
        assert convert_umf_format_to_duckdb("MM/DD/YYYY") == "%m/%d/%Y"

    def test_compact_date(self):
        assert convert_umf_format_to_duckdb("YYYYMMDD") == "%Y%m%d"

    def test_iso_datetime(self):
        assert (
            convert_umf_format_to_duckdb("YYYY-MM-DD HH:MM:SS") == "%Y-%m-%d %H:%M:%S"
        )

    def test_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported UMF date/timestamp format"):
            convert_umf_format_to_duckdb("NOT-A-FORMAT")

    def test_registry_parity_identical_format_set(self):
        """Both converters MUST cover the identical set of registry formats.

        This is the guardrail for the agreed single-registry design: the Spark and
        DuckDB date converters are driven by the SAME SUPPORTED_DATE_FORMATS, so
        neither dialect may silently accept or reject a format the other does not.
        """
        registry_formats = {f.umf_format for f in SUPPORTED_DATE_FORMATS}

        duckdb_covered: set[str] = set()
        spark_covered: set[str] = set()
        for fmt in registry_formats:
            # Every registry format must convert cleanly in both dialects.
            assert convert_umf_format_to_duckdb(fmt)
            duckdb_covered.add(fmt)
            assert convert_umf_format_to_spark(fmt)
            spark_covered.add(fmt)

        assert duckdb_covered == registry_formats
        assert spark_covered == registry_formats
        assert duckdb_covered == spark_covered


class TestFormatConverterParity:
    """Spot-check that the spark and duckdb converters agree on tricky formats.

    Both are driven by the SAME SUPPORTED_DATE_FORMATS registry; this asserts that
    for tricky registry formats (compact, ISO-T, 12-hour AM/PM, fractional seconds)
    the duckdb strftime code actually round-trips a representative value via Python
    ``strptime`` (the duckdb engine uses the identical C strftime codes), and that
    the spark conversion produces the expected Java pattern. No JVM needed.
    """

    @pytest.mark.parametrize(
        ("umf_format", "sample", "spark_expected"),
        [
            ("YYYYMMDD", "20260131", "yyyyMMdd"),
            ("MMDDYYYY", "01312026", "MMddyyyy"),
            ("YYYY-MM-DDTHH:MM:SS", "2026-01-31T12:30:45", "yyyy-MM-dd'T'HH:mm:ss"),
            (
                "MM/DD/YYYY hh:mm:ss A",
                "01/31/2026 01:30:45 PM",
                "MM/dd/yyyy hh:mm:ss a",
            ),
            (
                "YYYY-MM-DD HH:MM:SS.SSSSSS",
                "2026-01-31 12:30:45.123456",
                "yyyy-MM-dd HH:mm:ss.SSSSSS",
            ),
        ],
    )
    def test_tricky_formats_parity(self, umf_format, sample, spark_expected):
        from datetime import datetime

        # Spark side: the converter yields the expected Java SimpleDateFormat pattern.
        assert convert_umf_format_to_spark(umf_format) == spark_expected
        # DuckDB side: the strftime code parses the representative sample value
        # (DuckDB's try_strptime uses the identical C strftime codes).
        duck = convert_umf_format_to_duckdb(umf_format)
        assert datetime.strptime(sample, duck) is not None


class TestConvertUmfFormatToSpark:
    """Test UMF format to Spark SimpleDateFormat conversion."""

    def test_iso_date(self):
        """YYYY-MM-DD converts to yyyy-MM-dd."""
        assert convert_umf_format_to_spark("YYYY-MM-DD") == "yyyy-MM-dd"

    def test_us_date_slashes(self):
        """MM/DD/YYYY converts to MM/dd/yyyy."""
        assert convert_umf_format_to_spark("MM/DD/YYYY") == "MM/dd/yyyy"

    def test_us_date_dashes(self):
        """MM-DD-YYYY converts to MM-dd-yyyy."""
        assert convert_umf_format_to_spark("MM-DD-YYYY") == "MM-dd-yyyy"

    def test_compact_date(self):
        """YYYYMMDD converts to yyyyMMdd."""
        assert convert_umf_format_to_spark("YYYYMMDD") == "yyyyMMdd"

    def test_timestamp_with_seconds(self):
        """YYYY-MM-DD HH:MM:SS converts correctly with minutes as mm."""
        result = convert_umf_format_to_spark("YYYY-MM-DD HH:MM:SS")
        assert result == "yyyy-MM-dd HH:mm:ss"

    def test_timestamp_iso_t_separator(self):
        """ISO timestamp with T separator gets quoted T."""
        result = convert_umf_format_to_spark("YYYY-MM-DDTHH:MM:SS")
        assert result == "yyyy-MM-dd'T'HH:mm:ss"

    def test_two_digit_year(self):
        """YY converts to yy."""
        assert convert_umf_format_to_spark("MM/DD/YY") == "MM/dd/yy"

    def test_non_padded_month_day(self):
        """M/D/YYYY converts to M/d/yyyy."""
        assert convert_umf_format_to_spark("M/D/YYYY") == "M/d/yyyy"

    def test_12_hour_with_ampm(self):
        """12-hour format with AM/PM marker."""
        result = convert_umf_format_to_spark("MM/DD/YYYY hh:mm:ss A")
        assert result == "MM/dd/yyyy hh:mm:ss a"

    def test_fractional_seconds_preserved(self):
        """Fractional seconds (.SSSSSS) stay uppercase."""
        result = convert_umf_format_to_spark("YYYY-MM-DD HH:MM:SS.SSSSSS")
        assert result == "yyyy-MM-dd HH:mm:ss.SSSSSS"

    def test_timestamp_lowercase_minutes(self):
        """Lowercase mm for minutes in UMF format."""
        result = convert_umf_format_to_spark("YYYY-MM-DD HH:mm:ss")
        assert result == "yyyy-MM-dd HH:mm:ss"

    def test_non_padded_hour_24(self):
        """Non-padded 24-hour format H."""
        result = convert_umf_format_to_spark("YYYY-MM-DD H:MM:SS")
        assert result == "yyyy-MM-dd H:mm:ss"

    def test_non_padded_hour_12(self):
        """Non-padded 12-hour format h."""
        result = convert_umf_format_to_spark("M/D/YYYY h:mm A")
        assert result == "M/d/yyyy h:mm a"

    def test_mmddyyyy_compact(self):
        """MMDDYYYY converts to MMddyyyy."""
        assert convert_umf_format_to_spark("MMDDYYYY") == "MMddyyyy"


class TestCommonFormats:
    """Test that format tuples are defined and non-empty."""

    def test_common_date_formats_not_empty(self):
        """COMMON_DATE_FORMATS is a non-empty tuple."""
        assert isinstance(COMMON_DATE_FORMATS, tuple)
        assert len(COMMON_DATE_FORMATS) > 0

    def test_common_timestamp_formats_not_empty(self):
        """COMMON_TIMESTAMP_FORMATS is a non-empty tuple."""
        assert isinstance(COMMON_TIMESTAMP_FORMATS, tuple)
        assert len(COMMON_TIMESTAMP_FORMATS) > 0

    def test_date_formats_are_strings(self):
        """All date formats are strings."""
        for fmt in COMMON_DATE_FORMATS:
            assert isinstance(fmt, str)

    def test_timestamp_formats_are_strings(self):
        """All timestamp formats are strings."""
        for fmt in COMMON_TIMESTAMP_FORMATS:
            assert isinstance(fmt, str)


class TestBuildFlexibleFormats:
    """Test build_flexible_formats for date/timestamp format priority."""

    def test_date_with_primary(self):
        """Primary format comes first for DATE."""
        result = build_flexible_formats("DATE", "MM/DD/YYYY")
        assert result[0] == "MM/DD/YYYY"
        assert len(result) > 1

    def test_timestamp_with_primary(self):
        """Primary format comes first for TIMESTAMP."""
        result = build_flexible_formats("TIMESTAMP", "YYYY-MM-DD HH:MM:SS")
        assert result[0] == "YYYY-MM-DD HH:MM:SS"
        assert len(result) > 1

    def test_no_primary(self):
        """None primary still returns formats."""
        result = build_flexible_formats("DATE", None)
        assert len(result) > 0

    def test_unsupported_type_returns_empty(self):
        """Non-date/timestamp types return empty list."""
        assert build_flexible_formats("INTEGER", "whatever") == []
        assert build_flexible_formats("STRING", None) == []

    def test_no_duplicates(self):
        """Returned list has no duplicate formats."""
        result = build_flexible_formats("DATE", "YYYY-MM-DD")
        assert len(result) == len(set(result))

    def test_fallback_formats_included(self):
        """Fallback formats appear after primary."""
        result = build_flexible_formats(
            "DATE", "YYYY-MM-DD", ["MM/DD/YYYY", "YYYYMMDD"]
        )
        assert result[0] == "YYYY-MM-DD"
        idx_mm = result.index("MM/DD/YYYY")
        idx_compact = result.index("YYYYMMDD")
        assert idx_mm < idx_compact  # fallback order preserved
        assert idx_mm > 0  # after primary

    def test_case_insensitive_type(self):
        """Target type is case-insensitive."""
        result_lower = build_flexible_formats("date", "YYYY-MM-DD")
        result_upper = build_flexible_formats("DATE", "YYYY-MM-DD")
        assert result_lower == result_upper

    def test_common_date_formats_included(self):
        """COMMON_DATE_FORMATS entries appear in result for DATE type."""
        result = build_flexible_formats("DATE", None)
        for fmt in COMMON_DATE_FORMATS:
            assert fmt in result


class TestSparkDependentFunctions:
    """Test that PySpark-dependent functions handle missing PySpark."""

    def test_cast_column_with_format_raises_without_spark(self, monkeypatch):
        """cast_column_with_format raises ImportError when SPARK_AVAILABLE is False."""
        import tablespec.casting_utils as mod

        monkeypatch.setattr(mod, "SPARK_AVAILABLE", False)
        with pytest.raises(ImportError, match="PySpark is required"):
            mod.cast_column_with_format(None, "DATE", "YYYY-MM-DD")

    def test_is_excel_serial_date_raises_without_spark(self, monkeypatch):
        """is_excel_serial_date raises ImportError when SPARK_AVAILABLE is False."""
        import tablespec.casting_utils as mod

        monkeypatch.setattr(mod, "SPARK_AVAILABLE", False)
        with pytest.raises(ImportError, match="PySpark is required"):
            mod.is_excel_serial_date(None)

    def test_convert_excel_serial_to_date_raises_without_spark(self, monkeypatch):
        """convert_excel_serial_to_date raises ImportError when SPARK_AVAILABLE is False."""
        import tablespec.casting_utils as mod

        monkeypatch.setattr(mod, "SPARK_AVAILABLE", False)
        with pytest.raises(ImportError, match="PySpark is required"):
            mod.convert_excel_serial_to_date(None)
