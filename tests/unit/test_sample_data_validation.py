# SPDX-License-Identifier: MIT OR Apache-2.0
"""Unit tests for sample_data.validation module - ValidationRuleProcessor."""

import re

import pytest

from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.generators import HealthcareDataGenerators
from tablespec.sample_data.validation import ValidationRuleProcessor

pytestmark = pytest.mark.fast


@pytest.fixture
def config():
    return GenerationConfig(random_seed=42)


@pytest.fixture
def generators(config):
    return HealthcareDataGenerators(config=config)


@pytest.fixture
def processor(generators):
    return ValidationRuleProcessor(generators)


class TestValueConstraints:
    def test_enumerated_values(self, processor):
        rules = {
            "value_constraints": ["Valid values: MEDICAID, MEDICARE, DUALS"],
        }
        result = processor.apply_validation_rules("lob", rules)
        assert result in ["MEDICAID", "MEDICARE", "DUALS"]

    def test_enumerated_values_single(self, processor):
        rules = {
            "value_constraints": ["Valid values: ACTIVE"],
        }
        result = processor.apply_validation_rules("status", rules)
        assert result == "ACTIVE"

    def test_no_valid_values_prefix(self, processor):
        rules = {
            "value_constraints": ["Must be non-negative"],
        }
        result = processor.apply_validation_rules("amount", rules)
        assert result is None


class TestFormatRules:
    def test_plan_code_format(self, processor):
        rules = {
            "format_rules": ["Plan code: 2 digit length+Amisys number"],
        }
        result = processor.apply_validation_rules("plan_code", rules)
        assert re.fullmatch(r"\d{2}A\d{4}", result)

    def test_medicare_member_id(self, processor):
        rules = {
            "format_rules": ["Medicare Member ID format"],
        }
        result = processor.apply_validation_rules("member_id", rules)
        assert isinstance(result, str)
        assert len(result) == 11

    def test_medicaid_member_id(self, processor):
        rules = {
            "format_rules": ["Medicaid Member ID format"],
        }
        result = processor.apply_validation_rules("member_id", rules)
        assert result.startswith("MCD")

    def test_digit_count_format(self, processor):
        rules = {
            "format_rules": ["Always 10 digit identifier"],
        }
        result = processor.apply_validation_rules("npi", rules)
        assert len(result) == 10
        assert result.isdigit()


class TestLengthConstraints:
    def test_exact_length(self, processor):
        rules = {
            "length_constraints": ["Exactly 5 characters"],
        }
        result = processor.apply_validation_rules("zip_code", rules)
        assert len(result) == 5
        assert result.isdigit()


class TestBusinessRules:
    def test_icd_code(self, processor):
        rules = {
            "business_rules": ["Must be valid ICD-10 code"],
        }
        result = processor.apply_validation_rules("diagnosis", rules)
        assert isinstance(result, str)
        # ICD-10 format: Letter + 2 digits + . + digit
        assert re.fullmatch(r"[A-Z]\d{2}\.\d", result)


class TestConditionalRules:
    def test_conditional_rules_logged(self, processor, caplog):
        import logging

        with caplog.at_level(logging.DEBUG):
            rules = {
                "conditional_rules": ["If LOB=MEDICARE then must have MBI"],
            }
            result = processor.apply_validation_rules("member_id", rules)
        assert result is None


class TestNoRulesApplied:
    def test_empty_rules(self, processor):
        result = processor.apply_validation_rules("col", {})
        assert result is None

    def test_unrecognized_rules(self, processor):
        rules = {
            "format_rules": ["Some unknown format requirement"],
        }
        result = processor.apply_validation_rules("col", rules)
        assert result is None


class TestErrorHandling:
    def test_exception_returns_none(self, processor, mocker):
        # Force an error by passing something that will cause issues
        rules = {"value_constraints": None}  # type: ignore[dict-item]
        result = processor.apply_validation_rules("col", rules)
        # Should return None (exception caught)
        assert result is None


class TestMedicareBeneficiaryId:
    def test_format(self, processor):
        mbi = processor._generate_medicare_id()
        assert len(mbi) == 11
        # Check alternating pattern: digits at even positions, letters at odd
        for i, char in enumerate(mbi):
            if i % 2 == 0:
                assert char.isdigit(), f"Position {i} should be digit, got {char}"
            else:
                assert char.isalpha(), f"Position {i} should be letter, got {char}"
                # Should not contain excluded letters
                assert char not in "BILOSZ"
