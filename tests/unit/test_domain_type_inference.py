# SPDX-License-Identifier: MIT OR Apache-2.0
"""Unit tests for domain type inference - DomainTypeRegistry and DomainTypeInference.

Covers loading, lookup, validation specs, sample generators, and inference matching.
Complements test_domain_type_compatibility.py which focuses on type compatibility.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tablespec.inference.domain_types import DomainTypeInference, DomainTypeRegistry

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# --- DomainTypeRegistry Tests ---


class TestDomainTypeRegistryLoading:
    """Test registry loading from YAML."""

    def test_loads_default_registry(self):
        registry = DomainTypeRegistry()
        # Should load at least several domain types
        types = registry.list_domain_types()
        assert len(types) > 5
        assert "us_state_code" in types
        assert "email" in types

    def test_loads_custom_registry(self, tmp_path: Path):
        custom = tmp_path / "custom_domains.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "domain_types": {
                        "custom_type": {
                            "name": "Custom",
                            "description": "A custom type",
                            "detection": {
                                "column_name_patterns": ["custom"],
                            },
                        }
                    }
                }
            )
        )
        registry = DomainTypeRegistry(registry_path=custom)
        assert registry.list_domain_types() == ["custom_type"]

    def test_missing_registry_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            DomainTypeRegistry(registry_path="/nonexistent/path.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("{{invalid yaml: [")
        with pytest.raises(ValueError, match="Failed to parse"):
            DomainTypeRegistry(registry_path=bad_yaml)

    def test_empty_domain_types(self, tmp_path: Path):
        empty = tmp_path / "empty.yaml"
        empty.write_text(yaml.dump({"domain_types": {}}))
        registry = DomainTypeRegistry(registry_path=empty)
        assert registry.list_domain_types() == []

    def test_missing_domain_types_key(self, tmp_path: Path):
        no_key = tmp_path / "nokey.yaml"
        no_key.write_text(yaml.dump({"other": "data"}))
        registry = DomainTypeRegistry(registry_path=no_key)
        assert registry.list_domain_types() == []


class TestDomainTypeRegistryLookup:
    """Test domain type lookup methods."""

    @pytest.fixture
    def registry(self) -> DomainTypeRegistry:
        return DomainTypeRegistry()

    def test_get_existing_domain_type(self, registry: DomainTypeRegistry):
        dt = registry.get_domain_type("us_state_code")
        assert dt is not None
        assert dt["name"] == "US State Code"

    def test_get_nonexistent_domain_type(self, registry: DomainTypeRegistry):
        assert registry.get_domain_type("nonexistent") is None

    def test_list_domain_types_returns_list(self, registry: DomainTypeRegistry):
        types = registry.list_domain_types()
        assert isinstance(types, list)
        assert all(isinstance(t, str) for t in types)


class TestDomainTypeRegistryValidationSpecs:
    """Test validation spec retrieval."""

    @pytest.fixture
    def registry(self) -> DomainTypeRegistry:
        return DomainTypeRegistry()

    def test_get_validation_specs_for_state_code(self, registry: DomainTypeRegistry):
        specs = registry.get_validation_specs("us_state_code")
        assert len(specs) >= 1
        # Should have an expect_column_values_to_be_in_set validation
        types = [s["type"] for s in specs]
        assert "expect_column_values_to_be_in_set" in types

    def test_get_validation_specs_for_nonexistent(self, registry: DomainTypeRegistry):
        specs = registry.get_validation_specs("nonexistent_domain")
        assert specs == []

    def test_get_validation_specs_for_unmapped(self, registry: DomainTypeRegistry):
        specs = registry.get_validation_specs("unmapped")
        assert len(specs) >= 1

    def test_backward_compat_singular_validation(self, tmp_path: Path):
        """Test backward compatibility with singular 'validation' key."""
        custom = tmp_path / "compat.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "domain_types": {
                        "old_style": {
                            "name": "Old Style",
                            "validation": {
                                "type": "expect_column_to_exist",
                                "kwargs": {"column": "__COL__"},
                                "severity": "info",
                            },
                        }
                    }
                }
            )
        )
        registry = DomainTypeRegistry(registry_path=custom)
        specs = registry.get_validation_specs("old_style")
        assert len(specs) == 1
        assert specs[0]["type"] == "expect_column_to_exist"


class TestDomainTypeRegistrySampleGenerator:
    """Test sample generator method retrieval."""

    @pytest.fixture
    def registry(self) -> DomainTypeRegistry:
        return DomainTypeRegistry()

    def test_state_code_has_generator(self, registry: DomainTypeRegistry):
        method = registry.get_sample_generator_method("us_state_code")
        assert method == "generate_state_code"

    def test_nonexistent_returns_none(self, registry: DomainTypeRegistry):
        assert registry.get_sample_generator_method("nonexistent") is None

    def test_domain_without_generator(self, tmp_path: Path):
        custom = tmp_path / "nogen.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "domain_types": {
                        "no_gen": {
                            "name": "No Generator",
                            "description": "Type without sample generation",
                        }
                    }
                }
            )
        )
        registry = DomainTypeRegistry(registry_path=custom)
        assert registry.get_sample_generator_method("no_gen") is None


# --- DomainTypeInference Tests ---


class TestDomainTypeInferenceMatching:
    """Test domain type inference from column metadata."""

    @pytest.fixture
    def inference(self) -> DomainTypeInference:
        return DomainTypeInference()

    def test_infer_state_code_from_name(self, inference: DomainTypeInference):
        domain_type, confidence = inference.infer_domain_type("member_state_code")
        assert domain_type == "us_state_code"
        assert confidence > 0.0

    def test_infer_zip_code_from_name(self, inference: DomainTypeInference):
        domain_type, confidence = inference.infer_domain_type("zip_code")
        assert domain_type == "zip_code"
        assert confidence > 0.0

    def test_infer_email_from_name(self, inference: DomainTypeInference):
        domain_type, confidence = inference.infer_domain_type("email_address")
        assert domain_type == "email"
        assert confidence > 0.0

    def test_no_match_returns_none(self, inference: DomainTypeInference):
        domain_type, confidence = inference.infer_domain_type("xyzzy_field_999")
        assert domain_type is None
        assert confidence == 0.0

    def test_description_boosts_confidence(self, inference: DomainTypeInference):
        # Name only
        _, conf_name_only = inference.infer_domain_type("state")
        # Name + description
        _, conf_with_desc = inference.infer_domain_type(
            "state", description="US state abbreviation"
        )
        # With description should have same or higher confidence
        assert conf_with_desc >= conf_name_only

    def test_sample_values_boost_confidence(self, inference: DomainTypeInference):
        # Name-based match
        _, conf_name = inference.infer_domain_type("mbr_st")
        # With matching sample values
        _, conf_samples = inference.infer_domain_type(
            "mbr_st", sample_values=["CA", "NY", "TX", "FL"]
        )
        assert conf_samples >= conf_name

    def test_sample_values_with_regex_pattern(self, inference: DomainTypeInference):
        """ZIP code detection should work with sample values matching pattern."""
        domain_type, confidence = inference.infer_domain_type(
            "postal_code", sample_values=["12345", "67890", "54321"]
        )
        assert domain_type == "zip_code"
        assert confidence > 0.0

    def test_non_matching_samples(self, inference: DomainTypeInference):
        """Samples that don't match pattern shouldn't boost confidence."""
        # "zip_code" name matches, but non-zip samples shouldn't add confidence
        _, conf_bad_samples = inference.infer_domain_type(
            "zip_code", sample_values=["not-a-zip", "also-not", "nope"]
        )
        _, conf_good_samples = inference.infer_domain_type(
            "zip_code", sample_values=["12345", "67890", "11111"]
        )
        assert conf_good_samples >= conf_bad_samples


class TestDomainTypeInferenceFuzzyMatch:
    """Test the fuzzy matching helper."""

    def test_exact_segment_match(self):
        assert DomainTypeInference._fuzzy_match("state", "member_state") is True

    def test_no_segment_match(self):
        assert DomainTypeInference._fuzzy_match("state", "mbr_first_name") is False

    def test_partial_segment_no_match(self):
        # "zip" should not match "unzipped" as a segment
        assert DomainTypeInference._fuzzy_match("zip", "unzipped") is False

    def test_single_segment_text(self):
        assert DomainTypeInference._fuzzy_match("email", "email") is True

    def test_pattern_at_start(self):
        assert DomainTypeInference._fuzzy_match("state", "state_code") is True

    def test_pattern_at_end(self):
        assert DomainTypeInference._fuzzy_match("code", "state_code") is True


class TestDomainTypeInferenceWithCustomRegistry:
    """Test inference with custom registry."""

    def test_custom_domain_type_detection(self, tmp_path: Path):
        custom = tmp_path / "custom.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "domain_types": {
                        "custom_id": {
                            "name": "Custom ID",
                            "description": "A custom identifier",
                            "detection": {
                                "column_name_patterns": ["custom_id", "cust_id"],
                                "description_keywords": ["custom identifier"],
                            },
                        }
                    }
                }
            )
        )
        registry = DomainTypeRegistry(registry_path=custom)
        inference = DomainTypeInference(registry=registry)

        domain_type, confidence = inference.infer_domain_type("custom_id")
        assert domain_type == "custom_id"
        assert confidence > 0.0

    def test_no_detection_rules_returns_zero(self, tmp_path: Path):
        custom = tmp_path / "nodetect.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "domain_types": {
                        "no_detect": {
                            "name": "No Detection",
                            "description": "Type without detection rules",
                        }
                    }
                }
            )
        )
        registry = DomainTypeRegistry(registry_path=custom)
        inference = DomainTypeInference(registry=registry)

        domain_type, confidence = inference.infer_domain_type("anything")
        assert domain_type is None
        assert confidence == 0.0
