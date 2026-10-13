"""Unit tests for Dynamic Foreign Key Pool Manager.

Tests the relationship-driven foreign key synchronization system using
real fixtures and stubs (no mocks).
"""

from collections import defaultdict

import pytest

from tablespec.sample_data import (
    DynamicValueGenerator,
    ForeignKeyPoolManager,
    GenerationConfig,
    RelationshipAnalyzer,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestRelationshipAnalyzer:
    """Test relationship analysis and equivalence group discovery."""

    @pytest.fixture
    def simple_umf_files(self):
        """Create minimal UMF data structures for testing equivalence groups."""
        return {
            "Table1": {
                "columns": [{"name": "ClientMemberID", "data_type": "STRING"}],
                "relationships": {
                    "outgoing": [
                        {
                            "source_column": "ClientMemberID",
                            "target_column": "CLIENT_MEMBER_ID",
                            "target_table": "Table2",
                        }
                    ]
                },
            },
            "Table2": {
                "columns": [{"name": "CLIENT_MEMBER_ID", "data_type": "STRING"}],
                "relationships": {
                    "incoming": [
                        {
                            "source_column": "ClientMemberID",
                            "source_table": "Table1",
                            "target_column": "CLIENT_MEMBER_ID",
                        }
                    ],
                    "outgoing": [
                        {
                            "source_column": "CLIENT_MEMBER_ID",
                            "target_column": "ClientMbrID",
                            "target_table": "Table3",
                        }
                    ],
                },
            },
            "Table3": {
                "columns": [{"name": "ClientMbrID", "data_type": "STRING"}],
                "relationships": {
                    "incoming": [
                        {
                            "source_column": "CLIENT_MEMBER_ID",
                            "source_table": "Table2",
                            "target_column": "ClientMbrID",
                        }
                    ]
                },
            },
        }

    @pytest.fixture
    def multiple_groups_umf_files(self):
        """Create UMF data with multiple independent equivalence groups."""
        return {
            "TableA": {
                "relationships": {
                    "outgoing": [
                        {
                            "source_column": "MemberID",
                            "target_column": "MemberId",
                            "target_table": "TableB",
                        }
                    ]
                }
            },
            "TableB": {
                "relationships": {
                    "incoming": [
                        {
                            "source_column": "MemberID",
                            "source_table": "TableA",
                            "target_column": "MemberId",
                        }
                    ]
                }
            },
            "TableC": {
                "relationships": {
                    "outgoing": [
                        {
                            "source_column": "PCP_NPI",
                            "target_column": "Provider_NPI",
                            "target_table": "TableD",
                        }
                    ]
                }
            },
            "TableD": {
                "relationships": {
                    "incoming": [
                        {
                            "source_column": "PCP_NPI",
                            "source_table": "TableC",
                            "target_column": "Provider_NPI",
                        }
                    ]
                }
            },
        }

    def test_discovers_single_equivalence_group_from_relationships(
        self, simple_umf_files
    ):
        """Test that transitive relationships create single equivalence group."""
        # This test will fail until we implement RelationshipAnalyzer
        analyzer = RelationshipAnalyzer()
        analyzer.analyze_umf_files(simple_umf_files)
        groups = analyzer.compute_equivalence_groups()

        # All three variants should be in one group
        assert len(groups) == 1
        group = next(iter(groups.values()))
        assert {"ClientMemberID", "CLIENT_MEMBER_ID", "ClientMbrID"} == group

    def test_handles_multiple_independent_groups(self, multiple_groups_umf_files):
        """Test that independent relationships create separate groups."""
        analyzer = RelationshipAnalyzer()
        analyzer.analyze_umf_files(multiple_groups_umf_files)
        groups = analyzer.compute_equivalence_groups()

        assert len(groups) == 2

        # Find member ID group
        member_group = None
        npi_group = None
        for group in groups.values():
            if "MemberID" in group:
                member_group = group
            elif "PCP_NPI" in group:
                npi_group = group

        assert member_group == {"MemberID", "MemberId"}
        assert npi_group == {"PCP_NPI", "Provider_NPI"}

    def test_handles_empty_relationships(self):
        """Test analyzer handles UMF files with no relationships."""
        empty_umf_files = {
            "TableX": {"columns": [{"name": "SomeColumn", "data_type": "STRING"}]}
        }

        analyzer = RelationshipAnalyzer()
        analyzer.analyze_umf_files(empty_umf_files)
        groups = analyzer.compute_equivalence_groups()

        assert len(groups) == 0


class TestForeignKeyPoolManager:
    """Test foreign key pool management with shared pools."""

    @pytest.fixture
    def test_config(self):
        """Test configuration with small pool size."""
        return GenerationConfig(
            key_pool_size=50, key_distribution_80_20=True, high_frequency_key_ratio=0.8
        )

    @pytest.fixture
    def stub_generator(self):
        """Simple stub generator that produces predictable values."""
        counter = {"value": 0}

        def generator():
            counter["value"] += 1
            return f"KEY_{counter['value']}"

        return generator

    def test_creates_single_pool_per_equivalence_group(
        self, test_config, stub_generator
    ):
        """Test that pool manager creates one pool per equivalence group."""
        pool_manager = ForeignKeyPoolManager(test_config)

        # Register equivalence group
        columns = {"CLIENT_ID", "ClientId", "client_id"}
        pool_manager.generate_pool("member_group", columns, stub_generator)

        # All variants should map to same logical pool
        assert pool_manager.get_value_for_column("CLIENT_ID") is not None
        assert pool_manager.get_value_for_column("ClientId") is not None
        assert pool_manager.get_value_for_column("client_id") is not None

        # Should have created exactly one pool
        assert len(pool_manager.pools) == 1

    def test_applies_80_20_distribution(self, test_config, stub_generator):
        """Test that pool manager applies 80/20 distribution correctly."""
        pool_manager = ForeignKeyPoolManager(test_config)
        columns = {"TestColumn"}
        pool_manager.generate_pool("test_group", columns, stub_generator)

        # Get many samples and verify distribution
        # Call start_new_record() before each sample to simulate different records
        # (per-record caching returns same value within a record)
        samples = []
        for _ in range(1000):
            pool_manager.start_new_record()
            samples.append(pool_manager.get_value_for_column("TestColumn"))

        # Count frequency of each value
        freq_counter = defaultdict(int)
        for sample in samples:
            freq_counter[sample] += 1

        # Verify 80/20 rule: top 20% of keys should get roughly 80% of selections
        sorted_freqs = sorted(freq_counter.values(), reverse=True)
        total_selections = sum(sorted_freqs)
        top_20_percent_count = max(1, len(sorted_freqs) // 5)
        top_selections = sum(sorted_freqs[:top_20_percent_count])

        # Should be roughly 80% (allow some variance for randomness)
        top_ratio = top_selections / total_selections
        assert 0.7 < top_ratio < 0.9


class TestDynamicValueGenerator:
    """Test dynamic value generation from UMF metadata."""

    @pytest.fixture
    def varchar_column_metadata(self):
        """Sample UMF column metadata for STRING field."""
        return {
            "name": "ClientMemberID",
            "data_type": "STRING",
            "length": 20,
            "sample_values": ["12345678901", "98765432109", "11111111111"],
        }

    @pytest.fixture
    def integer_column_metadata(self):
        """Sample UMF column metadata for INTEGER field."""
        return {
            "name": "TotalRank",
            "data_type": "INTEGER",
            "description": "Member's Tier Rank 1-6 for active outreach",
        }

    def test_generates_from_sample_values(self, varchar_column_metadata):
        """Test that generator uses sample values when available."""
        generator_func = DynamicValueGenerator().create_generator(
            varchar_column_metadata
        )

        # Generate multiple values
        generated_values = [generator_func() for _ in range(100)]

        # All generated values should be similar to samples (same pattern/length)
        set(varchar_column_metadata["sample_values"])
        for value in generated_values[:10]:  # Check first 10
            assert isinstance(value, str)
            assert len(value) == 11  # Same length as samples
            assert value.isdigit()  # Same pattern as samples

    def test_respects_data_type_constraints(self, integer_column_metadata):
        """Test that generator respects data type constraints."""
        generator_func = DynamicValueGenerator().create_generator(
            integer_column_metadata
        )

        generated_values = [generator_func() for _ in range(50)]

        # All values should be integers
        for value in generated_values:
            assert isinstance(value, int)
            # Based on description, should be in range 1-6 or higher for passive
            assert 1 <= value <= 120  # Allow for passive outreach values

    def test_handles_missing_metadata(self):
        """Test fallback generation when minimal metadata available."""
        minimal_metadata = {"name": "UnknownColumn", "data_type": "STRING"}

        generator_func = DynamicValueGenerator().create_generator(minimal_metadata)
        value = generator_func()

        # Should generate something reasonable
        assert isinstance(value, str)
        assert len(value) > 0


# All classes now imported from pulseflow_dev.generators.foreign_key_manager
