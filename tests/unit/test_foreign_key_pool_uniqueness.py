"""Unit tests for foreign key pool uniqueness enforcement."""

import pytest

from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.foreign_keys import (
    DynamicValueGenerator,
    ForeignKeyPoolManager,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def test_pool_generates_unique_values():
    """Test that FK pool enforces uniqueness when generating values."""
    config = GenerationConfig()
    pool_manager = ForeignKeyPoolManager(config)
    value_gen = DynamicValueGenerator()

    # Create generator for member ID pattern
    column_metadata = {
        "name": "ClientMbrID",
        "data_type": "STRING",
        "sample_values": ["AL98765432101"],
    }
    generator_func = value_gen.create_generator(column_metadata)

    # Generate pool with 100 unique values
    pool_size = 100
    pool_manager.generate_pool("test_group", {"ClientMbrID"}, generator_func, pool_size)

    # Verify pool has exactly 100 unique values
    pool = pool_manager.pools["test_group"]
    assert len(pool) == pool_size, f"Expected {pool_size} values, got {len(pool)}"
    assert len(set(pool)) == pool_size, "Pool contains duplicate values"


def test_pool_generates_member_id_pattern():
    """Test that generated member IDs follow the correct pattern."""
    value_gen = DynamicValueGenerator()

    column_metadata = {
        "name": "ClientMbrID",
        "data_type": "STRING",
        "sample_values": ["AL98765432101"],
    }
    generator_func = value_gen.create_generator(column_metadata)

    # Generate 10 values and verify pattern
    for _ in range(10):
        value = generator_func()
        assert len(value) == 13, f"Expected length 13, got {len(value)} for '{value}'"
        assert value[:2].isalpha(), f"First 2 chars should be letters: '{value}'"
        assert value[:2].isupper(), f"First 2 chars should be uppercase: '{value}'"
        assert value[2:].isdigit(), f"Last 11 chars should be digits: '{value}'"


def test_pool_size_respects_unique_constraints():
    """Test that pools for unique constraint columns are sized to max table rows."""
    config = GenerationConfig()
    config.key_pool_size = 500  # Default pool size

    pool_manager = ForeignKeyPoolManager(config)
    value_gen = DynamicValueGenerator()

    column_metadata = {
        "name": "ClientMbrID",
        "data_type": "STRING",
        "sample_values": ["AL98765432101"],
    }
    generator_func = value_gen.create_generator(column_metadata)

    # Generate pool with custom size (simulating unique constraint sizing)
    custom_size = 1000
    pool_manager.generate_pool(
        "test_group", {"ClientMbrID"}, generator_func, custom_size
    )

    # Verify pool uses custom size, not config default
    pool = pool_manager.pools["test_group"]
    assert len(pool) == custom_size, f"Expected {custom_size} values, got {len(pool)}"


def test_text_vs_string_data_type_handling():
    """Test that text-like and string data types are handled correctly."""
    value_gen = DynamicValueGenerator()

    # Test with TEXT
    text_metadata = {
        "name": "ClientMbrID",
        "data_type": "TEXT",
        "sample_values": ["AL98765432101"],
    }
    text_gen = value_gen.create_generator(text_metadata)
    text_value = text_gen()
    assert len(text_value) == 13, "TEXT should generate member ID pattern"

    # Test with STRING
    string_metadata = {
        "name": "ClientMbrID",
        "data_type": "STRING",
        "sample_values": ["AL98765432101"],
    }
    string_gen = value_gen.create_generator(string_metadata)
    string_value = string_gen()
    assert len(string_value) == 13, "STRING should generate member ID pattern"


def test_pool_warns_when_unable_to_generate_enough_unique_values():
    """Test that pool generation logs a warning if it can't generate enough unique values."""
    config = GenerationConfig()
    pool_manager = ForeignKeyPoolManager(config)

    # Create a generator that always returns the same value
    def constant_generator():
        return "SAME_VALUE"

    # Try to generate pool of 100 values with constant generator
    pool_size = 100
    pool_manager.generate_pool("test_group", {"TestCol"}, constant_generator, pool_size)

    # Pool should have only 1 unique value
    pool = pool_manager.pools["test_group"]
    assert len(set(pool)) == 1, "Pool should contain only 1 unique value"
    assert len(pool) < pool_size, (
        f"Pool should be smaller than requested size {pool_size}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
