# @covers US-036-AC1
import pytest

from tablespec.authoring.preview import generate_preview

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestGeneratePreview:
    def test_classifies_raw_expectations(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    },
                    {
                        "type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": "ssn", "regex": ".*"},
                    },
                ]
            }
        }
        result = generate_preview(data)
        assert len(result.raw) == 2
        assert len(result.ingested) == 0

    def test_classifies_ingested_expectations(self):
        data = {
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {"column": "age", "min_value": 0},
                        },
                        "severity": "critical",
                        "blocking": False,
                    }
                ]
            }
        }
        result = generate_preview(data)
        assert len(result.ingested) == 1
        assert result.ingested[0].severity == "critical"

    def test_flags_redundant(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {"type": "expect_column_to_exist", "kwargs": {"column": "id"}},
                ]
            }
        }
        result = generate_preview(data)
        assert len(result.redundant) == 1

    def test_empty_data(self):
        result = generate_preview({})
        assert result.total == 0

    def test_mixed_sources(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    },
                ]
            },
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {"column": "x", "min_value": 0},
                        },
                        "severity": "warning",
                        "blocking": False,
                    },
                ]
            },
        }
        result = generate_preview(data)
        assert len(result.raw) == 1
        assert len(result.ingested) == 1
        assert result.total == 2

    def test_preserves_severity_from_quality_checks(self):
        data = {
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {"column": "x"},
                        },
                        "severity": "error",
                        "blocking": True,
                    }
                ]
            }
        }
        result = generate_preview(data)
        assert result.ingested[0].severity == "error"

    def test_severity_from_meta(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                        "meta": {"severity": "critical"},
                    }
                ]
            }
        }
        result = generate_preview(data)
        assert result.raw[0].severity == "critical"

    def test_prefers_expectation_suite_over_legacy_quality_checks(self):
        data = {
            "expectations": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                        "meta": {"validation_stage": "raw", "severity": "critical"},
                    }
                ]
            },
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {"column": "age", "min_value": 0},
                        },
                        "severity": "warning",
                        "blocking": False,
                    }
                ]
            },
        }

        result = generate_preview(data)

        assert len(result.raw) == 1
        assert len(result.ingested) == 0
