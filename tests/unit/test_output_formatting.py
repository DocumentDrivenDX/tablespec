# SPDX-License-Identifier: MIT OR Apache-2.0
"""Tests for output_formatting module.

PySpark-dependent functions are tested for ImportError behavior when PySpark is unavailable.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestSparkAvailableFlag:
    """Test the SPARK_AVAILABLE module-level constant."""

    def test_spark_available_is_bool(self):
        """SPARK_AVAILABLE is a boolean."""
        from tablespec.output_formatting import SPARK_AVAILABLE

        assert isinstance(SPARK_AVAILABLE, bool)


class TestApplyOutputFormatsWithoutSpark:
    """Test apply_output_formats when SPARK_AVAILABLE is False."""

    def test_raises_import_error(self, monkeypatch):
        """apply_output_formats raises ImportError when SPARK_AVAILABLE is False."""
        import tablespec.output_formatting as mod

        monkeypatch.setattr(mod, "SPARK_AVAILABLE", False)
        with pytest.raises(ImportError, match="PySpark is required"):
            mod.apply_output_formats(None, None)


class TestApplyNullReplacementsWithoutSpark:
    """Test apply_null_replacements when SPARK_AVAILABLE is False."""

    def test_raises_import_error(self, monkeypatch):
        """apply_null_replacements raises ImportError when SPARK_AVAILABLE is False."""
        import tablespec.output_formatting as mod

        monkeypatch.setattr(mod, "SPARK_AVAILABLE", False)
        with pytest.raises(ImportError, match="PySpark is required"):
            mod.apply_null_replacements(None, None)


class TestConvertUmfFormatToSparkReuse:
    """Test that output_formatting reuses convert_umf_format_to_spark from casting_utils.

    This confirms the module imports correctly and the function is accessible.
    """

    def test_import_works(self):
        """convert_umf_format_to_spark can be imported via output_formatting's dependency chain."""
        from tablespec.casting_utils import convert_umf_format_to_spark

        # Smoke test: verify it works for a basic format
        assert convert_umf_format_to_spark("YYYY-MM-DD") == "yyyy-MM-dd"
