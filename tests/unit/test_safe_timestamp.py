"""Tests for safe_to_timestamp / safe_to_date and the _format_to_prefilter_regex helper."""

from __future__ import annotations

import re

import pytest

from tablespec.casting_utils import _format_to_prefilter_regex


@pytest.mark.fast
class TestFormatToPrefilterRegex:
    """Verify that _format_to_prefilter_regex produces working regex patterns."""

    def test_returns_anchored_pattern(self):
        regex = _format_to_prefilter_regex("yyyy-MM-dd")
        assert regex.startswith("^")
        assert regex.endswith("$")

    @pytest.mark.parametrize(
        "spark_format,valid,invalid",
        [
            (
                "yyyy-MM-dd",
                ["2024-01-15", "2024-1-5", "9999-12-31"],
                ["not-a-date", "abcd-ef-gh", "", "01/15/2024"],
            ),
            (
                "MM/dd/yyyy",
                ["01/15/2024", "1/5/2024", "13/32/2024"],
                ["hello", "2024-01-15"],
            ),
            (
                "yyyy-MM-dd HH:mm:ss",
                ["2024-01-15 14:30:00", "2024-1-5 9:5:0"],
                ["not-a-date", "2024-01-15"],
            ),
            (
                "MM/dd/yyyy hh:mm a",
                ["01/15/2024 10:30 AM", "1/5/2024 1:00 PM"],
                ["2024-01-15", "hello"],
            ),
            (
                "MM/dd/yy",
                ["01/15/24", "1/5/99"],
                ["01/15/2024", "hello"],
            ),
        ],
    )
    def test_format_matching(
        self, spark_format: str, valid: list[str], invalid: list[str]
    ):
        regex = _format_to_prefilter_regex(spark_format)
        compiled = re.compile(regex)
        for v in valid:
            assert compiled.match(v), (
                f"{v!r} should match {regex} (format={spark_format})"
            )
        for iv in invalid:
            assert not compiled.match(iv), (
                f"{iv!r} should NOT match {regex} (format={spark_format})"
            )

    def test_iso_with_quoted_t(self):
        regex = _format_to_prefilter_regex("yyyy-MM-dd'T'HH:mm:ss")
        compiled = re.compile(regex)
        assert compiled.match("2024-01-15T14:30:00")
        assert not compiled.match("2024-01-15 14:30:00")

    def test_fractional_seconds(self):
        regex = _format_to_prefilter_regex("yyyy-MM-dd HH:mm:ss.SSS")
        compiled = re.compile(regex)
        assert compiled.match("2024-01-15 14:30:00.123")
        assert not compiled.match("not-a-date")

    def test_semantic_invalid_passes_regex(self):
        """Regex is structural only — it cannot reject semantically invalid dates.

        This is a documented limitation: month 13, Feb 30, etc. pass the
        regex but will be rejected by the actual parser.  On Sail this
        means to_timestamp throws; on Spark, try_to_timestamp returns NULL.
        """
        regex = _format_to_prefilter_regex("yyyy-MM-dd")
        compiled = re.compile(regex)
        # Month 13 is structurally valid (digits in right places)
        assert compiled.match("2024-13-01")
        # Feb 30 is structurally valid
        assert compiled.match("2024-02-30")


class TestSafeToTimestampBranchSelection:
    """Verify that safe_to_timestamp selects the correct code path.

    These tests use mocking to verify branch logic without requiring
    a running Spark/Sail session.
    """

    def test_no_format_uses_try_to_timestamp(self, monkeypatch):
        """Without format, safe_to_timestamp should use try_to_timestamp on any backend."""
        import tablespec.casting_utils as cu

        calls = []

        class FakeColumn:
            __module__ = "pyspark.sql.connect.column"  # Simulate Sail

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", args))
                return "try_result"

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        result = cu.safe_to_timestamp(FakeColumn(), spark_format=None)
        assert result == "try_result"
        assert len(calls) == 1
        assert calls[0] == ("try_to_timestamp", ())

    def test_with_format_on_connect_uses_regex_path(self, monkeypatch):
        """With format on Spark Connect (no session), should use regex prefilter."""
        import tablespec.casting_utils as cu

        calls = []

        class FakeColumn:
            __module__ = "pyspark.sql.connect.column"

            def rlike(self, pattern):
                calls.append(("rlike", pattern))
                return self

        class FakeTimestamp:
            pass

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", args))
                return "try_result"

            @staticmethod
            def to_timestamp(col, fmt=None):
                calls.append(("to_timestamp", fmt))
                return FakeTimestamp()

            @staticmethod
            def when(cond, val):
                class WhenResult:
                    @staticmethod
                    def otherwise(other):
                        return "when_result"

                calls.append(("when",))
                return WhenResult()

            @staticmethod
            def lit(val):
                class LitResult:
                    @staticmethod
                    def cast(t):
                        return None

                return LitResult()

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        result = cu.safe_to_timestamp(FakeColumn(), spark_format="yyyy-MM-dd")
        assert result == "when_result"
        # Should NOT have called try_to_timestamp
        assert not any(c[0] == "try_to_timestamp" for c in calls)
        # Should have called rlike (regex prefilter) and to_timestamp
        assert any(c[0] == "rlike" for c in calls)
        assert any(c[0] == "to_timestamp" for c in calls)

    def test_with_format_on_classic_spark_uses_try_to_timestamp(self, monkeypatch):
        """With format on classic Spark (no session), should use try_to_timestamp directly."""
        import tablespec.casting_utils as cu

        calls = []

        class FakeColumn:
            __module__ = "pyspark.sql.column"  # Classic Spark

        class FakeLit:
            pass

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", len(args)))
                return "try_result"

            @staticmethod
            def lit(val):
                return FakeLit()

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        result = cu.safe_to_timestamp(FakeColumn(), spark_format="yyyy-MM-dd")
        assert result == "try_result"
        assert calls == [("try_to_timestamp", 1)]


class TestSafeToTimestampCapabilityPath:
    """Verify that safe_to_timestamp uses capability probing when spark is provided."""

    def test_with_format_capability_true_uses_try_to_timestamp(self, monkeypatch):
        """When capabilities say try_to_timestamp_with_format=True, use it directly."""
        import tablespec.casting_utils as cu
        import tablespec.session as sess

        calls = []

        class FakeColumn:
            __module__ = (
                "pyspark.sql.connect.column"  # Connect column, but capability says OK
            )

        class FakeLit:
            pass

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", len(args)))
                return "try_result"

            @staticmethod
            def lit(val):
                return FakeLit()

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        # Stub get_capabilities to report the feature works
        fake_spark = object()
        monkeypatch.setattr(
            sess,
            "get_capabilities",
            lambda s: {"try_to_timestamp_with_format": True},
        )

        result = cu.safe_to_timestamp(
            FakeColumn(), spark_format="yyyy-MM-dd", spark=fake_spark
        )
        assert result == "try_result"
        assert calls == [("try_to_timestamp", 1)]

    def test_with_format_capability_false_uses_regex_path(self, monkeypatch):
        """When capabilities say try_to_timestamp_with_format=False, use regex path."""
        import tablespec.casting_utils as cu
        import tablespec.session as sess

        calls = []

        class FakeColumn:
            __module__ = (
                "pyspark.sql.column"  # Classic module, but capability says broken
            )

            def rlike(self, pattern):
                calls.append(("rlike", pattern))
                return self

        class FakeTimestamp:
            pass

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", args))
                return "try_result"

            @staticmethod
            def to_timestamp(col, fmt=None):
                calls.append(("to_timestamp", fmt))
                return FakeTimestamp()

            @staticmethod
            def when(cond, val):
                class WhenResult:
                    @staticmethod
                    def otherwise(other):
                        return "when_result"

                calls.append(("when",))
                return WhenResult()

            @staticmethod
            def lit(val):
                class LitResult:
                    @staticmethod
                    def cast(t):
                        return None

                return LitResult()

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        fake_spark = object()
        monkeypatch.setattr(
            sess,
            "get_capabilities",
            lambda s: {"try_to_timestamp_with_format": False},
        )

        result = cu.safe_to_timestamp(
            FakeColumn(), spark_format="yyyy-MM-dd", spark=fake_spark
        )
        assert result == "when_result"
        assert not any(c[0] == "try_to_timestamp" for c in calls)
        assert any(c[0] == "rlike" for c in calls)
        assert any(c[0] == "to_timestamp" for c in calls)

    def test_capability_probing_result_is_cached(self, monkeypatch):
        """get_capabilities should cache the result per session id."""
        import tablespec.session as sess

        # Clear any existing cache
        monkeypatch.setattr(sess, "_session_capabilities", {})

        probe_count = 0

        def counting_probe(spark):
            nonlocal probe_count
            probe_count += 1
            return True  # Simulate success

        monkeypatch.setattr(sess, "_probe_try_to_timestamp_with_format", counting_probe)

        fake_spark = object()

        # First call should probe
        caps1 = sess.get_capabilities(fake_spark)
        assert caps1["try_to_timestamp_with_format"] is True
        assert probe_count == 1

        # Second call with same session should use cache
        caps2 = sess.get_capabilities(fake_spark)
        assert caps2["try_to_timestamp_with_format"] is True
        assert probe_count == 1  # No additional probe

        # Different session should probe again
        fake_spark_2 = object()
        caps3 = sess.get_capabilities(fake_spark_2)
        assert caps3["try_to_timestamp_with_format"] is True
        assert probe_count == 2

    def test_no_session_falls_back_to_column_detection(self, monkeypatch):
        """When spark=None, the legacy _is_spark_connect_column path is used."""
        import tablespec.casting_utils as cu

        calls = []

        class FakeColumn:
            __module__ = "pyspark.sql.column"  # Classic Spark

        class FakeLit:
            pass

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", len(args)))
                return "try_result"

            @staticmethod
            def lit(val):
                return FakeLit()

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        # No spark session provided — should use _is_spark_connect_column fallback
        result = cu.safe_to_timestamp(
            FakeColumn(), spark_format="yyyy-MM-dd", spark=None
        )
        assert result == "try_result"
        assert calls == [("try_to_timestamp", 1)]

    def test_safe_to_date_forwards_spark_param(self, monkeypatch):
        """safe_to_date should forward the spark parameter to safe_to_timestamp."""
        import tablespec.casting_utils as cu
        import tablespec.session as sess

        calls = []

        class FakeColumn:
            __module__ = "pyspark.sql.connect.column"

        class FakeLit:
            pass

        class FakeResult:
            @staticmethod
            def cast(t):
                calls.append(("cast", t))
                return "date_result"

        class FakeF:
            @staticmethod
            def try_to_timestamp(col, *args):
                calls.append(("try_to_timestamp", len(args)))
                return FakeResult()

            @staticmethod
            def lit(val):
                return FakeLit()

        monkeypatch.setattr(cu, "SPARK_AVAILABLE", True)
        monkeypatch.setattr(cu, "F", FakeF)

        fake_spark = object()
        monkeypatch.setattr(
            sess,
            "get_capabilities",
            lambda s: {"try_to_timestamp_with_format": True},
        )

        result = cu.safe_to_date(
            FakeColumn(), spark_format="yyyy-MM-dd", spark=fake_spark
        )
        assert result == "date_result"
        assert ("try_to_timestamp", 1) in calls
        assert ("cast", "date") in calls
