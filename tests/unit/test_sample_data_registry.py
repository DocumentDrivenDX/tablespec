"""Unit tests for sample_data.registry module - KeyRegistry."""

import pytest

from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.registry import KeyRegistry

pytestmark = pytest.mark.fast


@pytest.fixture
def config():
    return GenerationConfig(random_seed=42, key_pool_size=10)


@pytest.fixture
def registry(config):
    return KeyRegistry(config=config)


class TestKeyRegistryBasics:
    def test_initialization(self, registry):
        assert registry.primary_keys == {}
        assert registry.foreign_key_usage == {}

    def test_register_primary_key(self, registry):
        registry.register_primary_key("members", "M001")
        registry.register_primary_key("members", "M002")
        assert registry.primary_keys["members"] == ["M001", "M002"]

    def test_register_primary_key_multiple_tables(self, registry):
        registry.register_primary_key("members", "M001")
        registry.register_primary_key("claims", "C001")
        assert "M001" in registry.primary_keys["members"]
        assert "C001" in registry.primary_keys["claims"]


class TestGetForeignKey:
    def test_returns_none_when_no_keys(self, registry):
        result = registry.get_foreign_key("some_column")
        assert result is None

    def test_fallback_to_primary_keys(self, registry):
        registry.register_primary_key("members", "M001")
        result = registry.get_foreign_key("member_id")
        assert result == "M001"

    def test_tracks_one_to_one_usage(self, registry):
        registry.register_primary_key("members", "M001")
        registry.get_foreign_key("member_id", cardinality="one_to_one")
        assert registry.foreign_key_usage["M001"] == 1

    def test_tracks_1_to_1_usage(self, registry):
        registry.register_primary_key("members", "M001")
        registry.get_foreign_key("member_id", cardinality="1:1")
        assert registry.foreign_key_usage["M001"] == 1

    def test_no_tracking_for_many_to_many(self, registry):
        registry.register_primary_key("members", "M001")
        registry.get_foreign_key("member_id", cardinality="many_to_many")
        assert len(registry.foreign_key_usage) == 0

    def test_mandatory_logs_warning_when_empty(self, registry, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            result = registry.get_foreign_key("required_col", mandatory=True)
        assert result is None
        assert "No foreign key available" in caplog.text


class TestGetKeyFromPool:
    def test_returns_none_when_no_pool(self, registry):
        result = registry.get_key_from_pool("ClientMemberID")
        assert result is None


class TestWeightedDistribution:
    def test_creates_distribution(self, registry):
        weights = registry._create_weighted_distribution(10)
        assert len(weights) == 10
        assert abs(sum(weights) - 1.0) < 0.01

    def test_high_frequency_weights_larger(self, registry):
        weights = registry._create_weighted_distribution(10)
        # Top 20% (first 2) should have higher individual weights
        assert weights[0] > weights[-1]


class TestPreGenerateKeyPools:
    def test_no_umf_files_skips(self, registry, config):
        from tablespec.sample_data.generators import HealthcareDataGenerators

        gen = HealthcareDataGenerators(config=config)
        registry.pre_generate_key_pools(gen, umf_files=None)
        # Should not crash

    def test_with_umf_relationships(self, registry, config):
        from tablespec.sample_data.generators import HealthcareDataGenerators

        gen = HealthcareDataGenerators(config=config)
        umf_files = {
            "members": {
                "columns": [
                    {
                        "name": "member_id",
                        "data_type": "STRING",
                        "sample_values": ["AB12345678901"],
                    },
                ],
                "relationships": {
                    "outgoing": [
                        {
                            "source_column": "member_id",
                            "target_table": "claims",
                            "target_column": "member_id",
                        }
                    ],
                },
            },
            "claims": {
                "columns": [
                    {"name": "member_id", "data_type": "STRING"},
                    {"name": "claim_id", "data_type": "STRING"},
                ],
                "relationships": {
                    "incoming": [
                        {
                            "source_table": "members",
                            "source_column": "member_id",
                            "target_column": "member_id",
                        }
                    ],
                },
            },
        }
        registry.pre_generate_key_pools(gen, umf_files=umf_files)
        # Should have created a pool for member_id equivalence group
        assert len(registry.foreign_key_manager.pools) > 0

    def test_with_cross_pipeline_seeds(self, registry, config):
        from tablespec.sample_data.generators import HealthcareDataGenerators

        gen = HealthcareDataGenerators(config=config)
        umf_files = {
            "table_a": {
                "columns": [{"name": "col_x", "data_type": "STRING"}],
                "relationships": {
                    "outgoing": [
                        {
                            "source_column": "col_x",
                            "target_table": "table_b",
                            "target_column": "col_x",
                        }
                    ],
                },
            },
            "table_b": {
                "columns": [{"name": "col_x", "data_type": "STRING"}],
                "relationships": {},
            },
        }
        seeds = {"col_x": ["SEED1", "SEED2", "SEED3"]}
        registry.pre_generate_key_pools(
            gen, umf_files=umf_files, cross_pipeline_seeds=seeds
        )
        # Pool should contain the seed values
        for pool in registry.foreign_key_manager.pools.values():
            assert "SEED1" in pool
            assert "SEED2" in pool

    def test_with_unique_constraints_and_row_counts(self, registry, config):
        from tablespec.sample_data.generators import HealthcareDataGenerators

        gen = HealthcareDataGenerators(config=config)
        umf_files = {
            "members": {
                "columns": [{"name": "member_id", "data_type": "STRING"}],
                "unique_constraints": [["member_id"]],
                "relationships": {
                    "outgoing": [
                        {
                            "source_column": "member_id",
                            "target_table": "claims",
                            "target_column": "member_id",
                        }
                    ],
                },
            },
            "claims": {
                "columns": [{"name": "member_id", "data_type": "STRING"}],
                "relationships": {},
            },
        }
        row_counts = {"members": 20, "claims": 50}
        registry.pre_generate_key_pools(
            gen, umf_files=umf_files, table_row_counts=row_counts
        )
        # Pool should be sized to max row count (50)
        for pool in registry.foreign_key_manager.pools.values():
            assert len(pool) >= 20  # At least enough for the tables


class TestFindRepresentativeColumn:
    def test_prefers_column_with_sample_values(self, registry):
        columns = {"col_a", "col_b"}
        umf_files = {
            "table1": {
                "columns": [
                    {"name": "col_a", "data_type": "STRING"},
                    {
                        "name": "col_b",
                        "data_type": "STRING",
                        "sample_values": ["X", "Y"],
                    },
                ]
            }
        }
        result = registry._find_representative_column(columns, umf_files)
        assert result is not None
        assert result["name"] == "col_b"

    def test_returns_none_when_no_match(self, registry):
        columns = {"nonexistent"}
        umf_files = {"table1": {"columns": [{"name": "other_col"}]}}
        result = registry._find_representative_column(columns, umf_files)
        assert result is None
