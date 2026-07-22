import warnings

import pytest

from tablespec.expectation_migration import migrate_to_expectation_suite

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestMigrateValidationRules:
    def test_raw_expectations_get_raw_stage(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    }
                ]
            }
        }
        suite = migrate_to_expectation_suite(data)
        assert len(suite.expectations) == 1
        assert suite.expectations[0].meta.stage == "raw"

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
        suite = migrate_to_expectation_suite(data)
        assert suite.expectations[0].meta.severity == "critical"

    def test_blocking_defaults_false(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    }
                ]
            }
        }
        suite = migrate_to_expectation_suite(data)
        assert suite.expectations[0].meta.blocking is False

    def test_pending_expectations_migrated(self):
        data = {
            "validation_rules": {
                "pending_expectations": [
                    {
                        "type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": "ssn", "regex": ".*"},
                    }
                ]
            }
        }
        suite = migrate_to_expectation_suite(data)
        assert len(suite.pending) == 1
        assert suite.pending[0].meta.stage == "raw"


class TestMigrateQualityChecks:
    def test_quality_checks_get_ingested_stage(self):
        data = {
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {"column": "age", "min_value": 0},
                        },
                        "severity": "critical",
                        "blocking": True,
                        "tags": ["data_quality"],
                    }
                ]
            }
        }
        suite = migrate_to_expectation_suite(data)
        assert len(suite.expectations) == 1
        exp = suite.expectations[0]
        assert exp.meta.stage == "ingested"
        assert exp.meta.severity == "critical"
        assert exp.meta.blocking is True
        assert "data_quality" in exp.meta.tags

    def test_misclassified_raw_type_corrected(self):
        """A raw type in quality_checks gets reclassified to raw with warning."""
        data = {
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_match_regex",
                            "kwargs": {"column": "ssn", "regex": ".*"},
                        },
                        "severity": "warning",
                        "blocking": False,
                    }
                ]
            }
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            suite = migrate_to_expectation_suite(data)
            assert suite.expectations[0].meta.stage == "raw"
            assert any(
                "Reclassified to stage='raw'" in str(warning.message) for warning in w
            )

    def test_thresholds_preserved(self):
        data = {"quality_checks": {"checks": [], "thresholds": {"max_failures": 5}}}
        suite = migrate_to_expectation_suite(data)
        assert suite.thresholds == {"max_failures": 5}

    def test_alert_config_preserved(self):
        data = {
            "quality_checks": {
                "checks": [],
                "alert_config": {"email": "test@test.com"},
            }
        }
        suite = migrate_to_expectation_suite(data)
        assert suite.alert_config == {"email": "test@test.com"}


class TestMigrateBothSources:
    def test_combined_migration(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    },
                    {
                        "type": "expect_column_value_lengths_to_be_between",
                        "kwargs": {"column": "name", "max_value": 50},
                    },
                ]
            },
            "quality_checks": {
                "checks": [
                    {
                        "expectation": {
                            "type": "expect_column_values_to_be_between",
                            "kwargs": {
                                "column": "age",
                                "min_value": 0,
                                "max_value": 150,
                            },
                        },
                        "severity": "error",
                        "blocking": False,
                    }
                ]
            },
        }
        suite = migrate_to_expectation_suite(data)
        assert len(suite.raw) == 2
        assert len(suite.ingested) == 1
        assert len(suite.expectations) == 3


class TestMigrateEdgeCases:
    def test_empty_data(self):
        suite = migrate_to_expectation_suite({})
        assert len(suite.expectations) == 0

    def test_none_values(self):
        suite = migrate_to_expectation_suite(
            {"validation_rules": None, "quality_checks": None}
        )
        assert len(suite.expectations) == 0

    def test_unknown_type_warns(self):
        data = {
            "validation_rules": {
                "expectations": [
                    {"type": "expect_custom_thing", "kwargs": {"column": "x"}}
                ]
            }
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            suite = migrate_to_expectation_suite(data)
            assert (
                suite.expectations[0].meta.stage == "raw"
            )  # defaults to container's stage
            assert any(
                "Unknown expectation type" in str(warning.message) for warning in w
            )

    def test_idempotent(self):
        """Migrating already-migrated data produces same result."""
        data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                        "meta": {"severity": "critical", "validation_stage": "raw"},
                    }
                ]
            }
        }
        suite1 = migrate_to_expectation_suite(data)
        # Convert back to dict and re-migrate
        roundtripped = {
            "validation_rules": {
                "expectations": [e.to_gx_dict() for e in suite1.expectations]
            }
        }
        suite2 = migrate_to_expectation_suite(roundtripped)
        assert len(suite1.expectations) == len(suite2.expectations)
        assert suite1.expectations[0].type == suite2.expectations[0].type
        assert suite1.expectations[0].meta.stage == suite2.expectations[0].meta.stage
        assert (
            suite1.expectations[0].meta.severity == suite2.expectations[0].meta.severity
        )
