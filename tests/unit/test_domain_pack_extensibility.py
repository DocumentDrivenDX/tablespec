# @covers US-033-AC2
"""Tests for custom domain pack registration and use in sample data generation (US-013 AC-3).

Proves that:
1. Custom domain types can be registered via a custom YAML file
2. Custom generators can be wired through ColumnValueGenerator
3. Custom validation specs are returned by get_validation_specs()
"""

import re

import pytest
import yaml

from tablespec.inference.domain_types import DomainTypeRegistry
from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.generators import HealthcareDataGenerators

pytestmark = pytest.mark.fast

# -- fixtures ----------------------------------------------------------------

CUSTOM_DOMAIN_TYPES_YAML = {
    "domain_types": {
        "ticket_id": {
            "detection": {
                "column_name_patterns": ["ticket_id", "ticket_number"],
                "description_keywords": ["ticket", "support ticket"],
                "sample_value_pattern": r"^TKT-\d{6}$",
            },
            "validations": [
                {
                    "type": "expect_column_values_to_match_regex",
                    "kwargs": {"regex": r"^TKT-\d{6}$"},
                    "severity": "critical",
                },
            ],
            "sample_generation": {
                "method": "generate_ticket_id",
            },
        },
        "priority_level": {
            "detection": {
                "column_name_patterns": ["priority", "priority_level"],
                "description_keywords": ["priority"],
            },
            "validations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"value_set": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "severity": "warning",
                },
            ],
            "sample_generation": {
                "method": "generate_priority_level",
            },
        },
    },
}


@pytest.fixture
def custom_yaml_path(tmp_path):
    """Write the custom domain types YAML to a temp file and return its path."""
    path = tmp_path / "domain_types.yaml"
    path.write_text(yaml.dump(CUSTOM_DOMAIN_TYPES_YAML, default_flow_style=False))
    return path


@pytest.fixture
def custom_registry(custom_yaml_path):
    """Load a DomainTypeRegistry from the custom YAML file."""
    return DomainTypeRegistry(registry_path=custom_yaml_path)


@pytest.fixture
def custom_registry_from_data():
    """Load a DomainTypeRegistry from in-memory data (no file I/O)."""
    return DomainTypeRegistry(registry_data=CUSTOM_DOMAIN_TYPES_YAML)


class CustomGenerators(HealthcareDataGenerators):
    """Extends HealthcareDataGenerators with custom domain-pack methods."""

    def generate_ticket_id(self) -> str:
        """Generate a ticket ID matching ^TKT-\\d{6}$."""
        import random

        return f"TKT-{random.randint(0, 999999):06d}"

    def generate_priority_level(self) -> str:
        """Generate a priority level."""
        import random

        return random.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"])


# -- Test 1: Custom domain type registration ---------------------------------


class TestCustomDomainTypeRegistration:
    """Custom domain types loaded from YAML are accessible in the registry."""

    def test_custom_type_accessible_from_file(self, custom_registry):
        dt = custom_registry.get_domain_type("ticket_id")
        assert dt is not None
        assert dt["sample_generation"]["method"] == "generate_ticket_id"

    def test_custom_type_accessible_from_data(self, custom_registry_from_data):
        dt = custom_registry_from_data.get_domain_type("ticket_id")
        assert dt is not None
        assert dt["detection"]["sample_value_pattern"] == r"^TKT-\d{6}$"

    def test_lists_all_custom_types(self, custom_registry):
        types = custom_registry.list_domain_types()
        assert "ticket_id" in types
        assert "priority_level" in types
        assert len(types) == 2

    def test_unknown_type_returns_none(self, custom_registry):
        assert custom_registry.get_domain_type("nonexistent") is None


# -- Test 2: Custom generator integration ------------------------------------


class TestCustomGeneratorIntegration:
    """Custom generators are callable via domain type registry + getattr dispatch."""

    def test_generate_ticket_id_format(self):
        config = GenerationConfig(random_seed=42)
        gen = CustomGenerators(config=config)
        for _ in range(20):
            value = gen.generate_ticket_id()
            assert re.fullmatch(r"TKT-\d{6}", value), f"Bad ticket_id: {value}"

    def test_generate_priority_level_values(self):
        config = GenerationConfig(random_seed=42)
        gen = CustomGenerators(config=config)
        valid = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        for _ in range(50):
            assert gen.generate_priority_level() in valid

    def test_registry_method_resolves_on_custom_generators(self, custom_registry):
        """The registry returns the method name, and getattr finds it on CustomGenerators."""
        config = GenerationConfig(random_seed=42)
        gen = CustomGenerators(config=config)

        method_name = custom_registry.get_sample_generator_method("ticket_id")
        assert method_name == "generate_ticket_id"
        assert hasattr(gen, method_name)

        value = getattr(gen, method_name)()
        assert re.fullmatch(r"TKT-\d{6}", value)

    def test_registry_method_resolves_priority_level(self, custom_registry):
        config = GenerationConfig(random_seed=42)
        gen = CustomGenerators(config=config)

        method_name = custom_registry.get_sample_generator_method("priority_level")
        assert method_name == "generate_priority_level"

        value = getattr(gen, method_name)()
        assert value in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_missing_domain_type_returns_none(self, custom_registry):
        assert custom_registry.get_sample_generator_method("nonexistent") is None


# -- Test 3: Custom validation specs ----------------------------------------


class TestCustomValidationSpecs:
    """Custom domain types expose their validation specs through the registry."""

    def test_ticket_id_validation_specs(self, custom_registry):
        specs = custom_registry.get_validation_specs("ticket_id")
        assert len(specs) == 1
        spec = specs[0]
        assert spec["type"] == "expect_column_values_to_match_regex"
        assert spec["kwargs"]["regex"] == r"^TKT-\d{6}$"
        assert spec["severity"] == "critical"

    def test_priority_level_validation_specs(self, custom_registry):
        specs = custom_registry.get_validation_specs("priority_level")
        assert len(specs) == 1
        spec = specs[0]
        assert spec["type"] == "expect_column_values_to_be_in_set"
        assert spec["kwargs"]["value_set"] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert spec["severity"] == "warning"

    def test_unknown_type_returns_empty_specs(self, custom_registry):
        assert custom_registry.get_validation_specs("nonexistent") == []
