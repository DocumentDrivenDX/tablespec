"""Tests for the unified ExpectationSuite model (ADR-005)."""

from tablespec.models.umf import (
    Expectation,
    ExpectationMeta,
    ExpectationSuite,
    QualityCheck,
    QualityChecks,
    UMF,
    UMFColumn,
    ValidationRules,
)


# ---------------------------------------------------------------------------
# ExpectationMeta
# ---------------------------------------------------------------------------


class TestExpectationMeta:
    def test_to_gx_meta_defaults(self):
        meta = ExpectationMeta()
        result = meta.to_gx_meta()
        # stage "unknown" is omitted
        assert "validation_stage" not in result
        assert result["severity"] == "warning"
        assert "blocking" not in result
        assert "description" not in result
        assert "tags" not in result
        assert "generated_from" not in result

    def test_to_gx_meta_full(self):
        meta = ExpectationMeta(
            stage="raw",
            severity="critical",
            blocking=True,
            description="Must not be null",
            tags=["baseline", "shift-left"],
            generated_from="baseline",
        )
        result = meta.to_gx_meta()
        assert result == {
            "validation_stage": "raw",
            "severity": "critical",
            "blocking": True,
            "description": "Must not be null",
            "tags": ["baseline", "shift-left"],
            "generated_from": "baseline",
        }

    def test_to_gx_meta_roundtrip(self):
        original = ExpectationMeta(
            stage="ingested",
            severity="error",
            blocking=False,
            description="Range check",
            tags=["profiling"],
            generated_from="profiling",
        )
        gx = original.to_gx_meta()
        restored = ExpectationMeta.from_gx_meta(gx)
        assert restored.stage == original.stage
        assert restored.severity == original.severity
        assert restored.blocking == original.blocking
        assert restored.description == original.description
        assert restored.tags == original.tags
        assert restored.generated_from == original.generated_from

    def test_from_gx_meta_auto_classifies_raw(self):
        meta = ExpectationMeta.from_gx_meta(
            {}, expectation_type="expect_column_values_to_not_be_null"
        )
        assert meta.stage == "raw"

    def test_from_gx_meta_auto_classifies_ingested(self):
        meta = ExpectationMeta.from_gx_meta(
            {}, expectation_type="expect_column_values_to_be_between"
        )
        assert meta.stage == "ingested"

    def test_from_gx_meta_unknown_type(self):
        meta = ExpectationMeta.from_gx_meta(
            {}, expectation_type="expect_some_custom_thing"
        )
        assert meta.stage == "unknown"

    def test_from_gx_meta_explicit_stage_overrides_auto(self):
        """If validation_stage is already in meta, it should be used even if expectation_type would differ."""
        meta = ExpectationMeta.from_gx_meta(
            {"validation_stage": "ingested"},
            expectation_type="expect_column_values_to_not_be_null",
        )
        assert meta.stage == "ingested"

    def test_from_gx_meta_no_type_no_stage(self):
        meta = ExpectationMeta.from_gx_meta({})
        assert meta.stage == "unknown"


# ---------------------------------------------------------------------------
# Expectation
# ---------------------------------------------------------------------------


class TestExpectation:
    def test_to_gx_dict(self):
        exp = Expectation(
            type="expect_column_values_to_not_be_null",
            kwargs={"column": "member_id"},
            meta=ExpectationMeta(stage="raw", severity="critical"),
        )
        result = exp.to_gx_dict()
        assert result["type"] == "expect_column_values_to_not_be_null"
        assert result["kwargs"] == {"column": "member_id"}
        assert result["meta"]["validation_stage"] == "raw"
        assert result["meta"]["severity"] == "critical"

    def test_from_gx_dict(self):
        d = {
            "type": "expect_column_values_to_be_between",
            "kwargs": {"column": "age", "min_value": 0, "max_value": 150},
            "meta": {"severity": "error"},
        }
        exp = Expectation.from_gx_dict(d)
        assert exp.type == "expect_column_values_to_be_between"
        assert exp.kwargs["column"] == "age"
        assert exp.meta.severity == "error"
        # Auto-classified as ingested
        assert exp.meta.stage == "ingested"

    def test_from_gx_dict_with_expectation_type_key(self):
        """GX sometimes uses 'expectation_type' instead of 'type'."""
        d = {
            "expectation_type": "expect_column_values_to_match_regex",
            "kwargs": {"column": "ssn", "regex": r"^\d{9}$"},
        }
        exp = Expectation.from_gx_dict(d)
        assert exp.type == "expect_column_values_to_match_regex"
        assert exp.meta.stage == "raw"

    def test_roundtrip(self):
        original = Expectation(
            type="expect_column_values_to_not_be_null",
            kwargs={"column": "member_id"},
            meta=ExpectationMeta(
                stage="raw",
                severity="critical",
                blocking=True,
                description="PK not null",
                tags=["pk"],
                generated_from="baseline",
            ),
        )
        gx_dict = original.to_gx_dict()
        restored = Expectation.from_gx_dict(gx_dict)
        assert restored.type == original.type
        assert restored.kwargs == original.kwargs
        assert restored.meta.stage == original.meta.stage
        assert restored.meta.severity == original.meta.severity
        assert restored.meta.blocking == original.meta.blocking
        assert restored.meta.description == original.meta.description
        assert restored.meta.tags == original.meta.tags
        assert restored.meta.generated_from == original.meta.generated_from


# ---------------------------------------------------------------------------
# ExpectationSuite
# ---------------------------------------------------------------------------


class TestExpectationSuite:
    def _make_suite(self) -> ExpectationSuite:
        return ExpectationSuite(
            expectations=[
                Expectation(
                    type="expect_column_values_to_not_be_null",
                    kwargs={"column": "id"},
                    meta=ExpectationMeta(stage="raw"),
                ),
                Expectation(
                    type="expect_column_values_to_match_regex",
                    kwargs={"column": "ssn", "regex": r"^\d{9}$"},
                    meta=ExpectationMeta(stage="raw"),
                ),
                Expectation(
                    type="expect_column_values_to_be_between",
                    kwargs={"column": "age", "min_value": 0, "max_value": 150},
                    meta=ExpectationMeta(stage="ingested"),
                ),
                Expectation(
                    type="expect_some_custom_thing",
                    kwargs={"column": "foo"},
                    meta=ExpectationMeta(stage="unknown"),
                ),
            ]
        )

    def test_raw_property(self):
        suite = self._make_suite()
        raw = suite.raw
        assert len(raw) == 2
        assert all(e.meta.stage == "raw" for e in raw)

    def test_ingested_property(self):
        suite = self._make_suite()
        ingested = suite.ingested
        assert len(ingested) == 1
        assert ingested[0].type == "expect_column_values_to_be_between"

    def test_unclassified_property(self):
        suite = self._make_suite()
        unclassified = suite.unclassified
        assert len(unclassified) == 1
        assert unclassified[0].type == "expect_some_custom_thing"

    def test_empty_suite(self):
        suite = ExpectationSuite()
        assert suite.raw == []
        assert suite.ingested == []
        assert suite.unclassified == []
        assert suite.expectations == []
        assert suite.pending == []

    def test_thresholds_and_alert_config(self):
        suite = ExpectationSuite(
            thresholds={"critical_count": 0, "error_rate": 0.05},
            alert_config={"channel": "#data-quality"},
        )
        assert suite.thresholds["critical_count"] == 0
        assert suite.alert_config["channel"] == "#data-quality"


# ---------------------------------------------------------------------------
# UMF integration
# ---------------------------------------------------------------------------

MINIMAL_COLUMNS = [
    UMFColumn(name="id", data_type="INTEGER", description="Primary key"),
]


class TestUMFIntegration:
    def test_umf_with_expectations_field(self):
        suite = ExpectationSuite(
            expectations=[
                Expectation(
                    type="expect_column_values_to_not_be_null",
                    kwargs={"column": "id"},
                    meta=ExpectationMeta(stage="raw"),
                ),
            ]
        )
        umf = UMF(
            version="1.0",
            table_name="test_table",
            columns=MINIMAL_COLUMNS,
            expectations=suite,
        )
        assert umf.expectations is not None
        assert len(umf.expectations.raw) == 1

    def test_umf_without_expectations(self):
        umf = UMF(
            version="1.0",
            table_name="test_table",
            columns=MINIMAL_COLUMNS,
        )
        assert umf.expectations is None

    def test_backward_compat_validation_rules_only(self):
        umf = UMF(
            version="1.0",
            table_name="test_table",
            columns=MINIMAL_COLUMNS,
            validation_rules=ValidationRules(
                expectations=[
                    {
                        "expectation_type": "expect_column_values_to_not_be_null",
                        "kwargs": {"column": "id"},
                    }
                ]
            ),
        )
        assert umf.validation_rules is not None
        assert len(umf.validation_rules.expectations) == 1
        assert umf.expectations is None

    def test_backward_compat_quality_checks_only(self):
        umf = UMF(
            version="1.0",
            table_name="test_table",
            columns=MINIMAL_COLUMNS,
            quality_checks=QualityChecks(
                checks=[
                    QualityCheck(
                        expectation={
                            "expectation_type": "expect_column_values_to_be_between",
                            "kwargs": {
                                "column": "id",
                                "min_value": 0,
                                "max_value": 100,
                            },
                        },
                        severity="warning",
                    )
                ]
            ),
        )
        assert umf.quality_checks is not None
        assert len(umf.quality_checks.checks) == 1
        assert umf.expectations is None

    def test_umf_with_all_three(self):
        """All three fields can coexist during migration."""
        umf = UMF(
            version="1.0",
            table_name="test_table",
            columns=MINIMAL_COLUMNS,
            validation_rules=ValidationRules(expectations=[]),
            quality_checks=QualityChecks(checks=[]),
            expectations=ExpectationSuite(expectations=[]),
        )
        assert umf.validation_rules is not None
        assert umf.quality_checks is not None
        assert umf.expectations is not None
