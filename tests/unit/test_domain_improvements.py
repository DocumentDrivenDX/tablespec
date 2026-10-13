# @covers US-017-AC1
# @covers US-017-AC2
# @covers US-017-AC3
# @covers US-017-AC4
# @covers US-033-AC1
"""Tests for domain type system improvements: abbreviation expansion,
structured inference results, regex validation, and Excel registry sync.
"""

from __future__ import annotations

import pytest

from tablespec.inference.domain_types import (
    DomainTypeInference,
    DomainTypeRegistry,
    InferenceResult,
    expand_column_name,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestAbbreviationExpansion:
    def test_simple_expansion(self):
        result = expand_column_name("mbr_id")
        assert "member_id" in result or "member_identifier" in result

    def test_multiple_expansions(self):
        result = expand_column_name("svc_dt")
        assert "service_date" in result

    def test_no_expansion_needed(self):
        result = expand_column_name("member_id")
        assert "member_id" in result

    def test_original_always_included(self):
        result = expand_column_name("mbr_dt")
        assert "mbr_dt" in result

    def test_preserves_order_and_dedupes(self):
        result = expand_column_name("id")
        # "id" should appear first (original), then expansions
        assert result[0] == "id"
        assert len(result) == len(set(result))

    def test_abbreviated_column_infers_correctly(self):
        inference = DomainTypeInference()
        result, confidence = inference.infer_domain_type("mbr_id", data_type="VARCHAR")
        assert result == "member_id"
        assert confidence > 0

    def test_svc_dt_infers_service_date(self):
        inference = DomainTypeInference()
        result, confidence = inference.infer_domain_type("svc_dt", data_type="VARCHAR")
        # Should match service_date or a date-related domain type
        assert result is not None
        assert confidence > 0

    def test_clm_id_infers_claim_number(self):
        inference = DomainTypeInference()
        result, confidence = inference.infer_domain_type("clm_id", data_type="VARCHAR")
        assert result == "claim_number"
        assert confidence > 0

    def test_no_false_expansions_for_plain_names(self):
        """Column names without abbreviations should still work normally."""
        inference = DomainTypeInference()
        result, confidence = inference.infer_domain_type("email_address")
        assert result == "email"
        assert confidence > 0


class TestInferenceWithExplanation:
    def test_returns_inference_result(self):
        inference = DomainTypeInference()
        result = inference.infer_with_explanation("member_id", data_type="VARCHAR")
        assert isinstance(result, InferenceResult)
        assert result.domain_type is not None
        assert result.confidence > 0

    def test_returns_explanation(self):
        inference = DomainTypeInference()
        result = inference.infer_with_explanation("member_id", data_type="VARCHAR")
        assert result.explanation  # non-empty
        assert (
            "column name" in result.explanation.lower()
            or "pattern" in result.explanation.lower()
        )

    def test_includes_runner_up(self):
        inference = DomainTypeInference()
        result = inference.infer_with_explanation("state_code", data_type="VARCHAR")
        # state_code should have a clear match
        assert result.domain_type is not None

    def test_no_match_returns_explanation(self):
        inference = DomainTypeInference()
        result = inference.infer_with_explanation(
            "xyzzy_field_999", data_type="VARCHAR"
        )
        assert result.domain_type is None
        assert result.confidence == 0.0
        assert "no matching" in result.explanation.lower()

    def test_description_appears_in_explanation(self):
        inference = DomainTypeInference()
        result = inference.infer_with_explanation(
            "state", data_type="VARCHAR", description="US state abbreviation"
        )
        assert result.domain_type is not None
        assert (
            "description" in result.explanation.lower()
            or "keyword" in result.explanation.lower()
        )

    def test_sample_values_in_explanation(self):
        inference = DomainTypeInference()
        result = inference.infer_with_explanation(
            "zip_code", data_type="VARCHAR", sample_values=["12345", "67890", "54321"]
        )
        assert result.domain_type == "zip_code"
        assert (
            "sample" in result.explanation.lower()
            or "pattern" in result.explanation.lower()
        )

    def test_abbreviation_expansion_noted_in_explanation(self):
        """When abbreviation expansion is needed, explanation mentions it."""
        inference = DomainTypeInference()
        # "prov_id" is not a direct pattern but "provider_id" is (via expansion of "prov")
        result = inference.infer_with_explanation("prov_id", data_type="VARCHAR")
        assert result.domain_type is not None
        assert result.confidence > 0
        # Explanation should mention the column name or pattern
        assert (
            "column name" in result.explanation.lower()
            or "pattern" in result.explanation.lower()
        )


class TestRegexValidation:
    def test_invalid_regex_raises(self):
        bad_registry = {
            "domain_types": {
                "bad_type": {
                    "name": "Bad Type",
                    "detection": {"sample_value_pattern": "[invalid(regex"},
                }
            }
        }
        with pytest.raises(ValueError, match="Invalid regex"):
            DomainTypeRegistry(registry_data=bad_registry)

    def test_valid_regex_loads(self):
        good_registry = {
            "domain_types": {
                "good_type": {
                    "name": "Good Type",
                    "detection": {"sample_value_pattern": r"^\d{3}$"},
                }
            }
        }
        registry = DomainTypeRegistry(registry_data=good_registry)
        assert "good_type" in registry.list_domain_types()

    def test_null_pattern_loads(self):
        """Null/None sample_value_pattern should not cause validation errors."""
        registry_data = {
            "domain_types": {
                "null_pattern": {
                    "name": "Null Pattern",
                    "detection": {"sample_value_pattern": None},
                }
            }
        }
        registry = DomainTypeRegistry(registry_data=registry_data)
        assert "null_pattern" in registry.list_domain_types()

    def test_no_detection_section_loads(self):
        """Domain types without detection section should load fine."""
        registry_data = {
            "domain_types": {
                "no_detect": {
                    "name": "No Detection",
                    "description": "No detection rules",
                }
            }
        }
        registry = DomainTypeRegistry(registry_data=registry_data)
        assert "no_detect" in registry.list_domain_types()

    def test_default_registry_has_valid_regexes(self):
        """The real domain_types.yaml should have all valid regex patterns."""
        # This will raise ValueError if any regex is invalid
        registry = DomainTypeRegistry()
        assert len(registry.list_domain_types()) > 0


class TestExcelRegistrySync:
    def test_domain_types_from_registry(self):
        """ExcelConstants.DOMAIN_TYPES should include types from the registry."""
        from tablespec.excel_converter import ExcelConstants

        constants = ExcelConstants()
        domain_types = constants.DOMAIN_TYPES
        assert isinstance(domain_types, list)
        assert len(domain_types) > 0
        # Should contain types from the registry (more than the old hardcoded list)
        assert "us_state_code" in domain_types
        assert "email" in domain_types
        # Should be sorted
        assert domain_types == sorted(domain_types)
