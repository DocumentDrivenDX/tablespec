"""Key registry for managing primary and foreign keys across tables."""

from collections import defaultdict
import logging
import random
from typing import TYPE_CHECKING, Any

from .foreign_keys import (
    DynamicValueGenerator,
    ForeignKeyPoolManager,
    RelationshipAnalyzer,
)

if TYPE_CHECKING:
    from tablespec import GXConstraintExtractor

    from .config import GenerationConfig
    from .generators import HealthcareDataGenerators


class KeyRegistry:
    """Manages primary and foreign keys across tables with relationship-driven pools."""

    def __init__(
        self,
        config: "GenerationConfig",
        gx_extractor: "GXConstraintExtractor | None" = None,
    ) -> None:
        self.config = config
        self.primary_keys: dict[str, list[str | int | float]] = defaultdict(list)
        self.foreign_key_usage: dict[str, int] = defaultdict(int)

        # New relationship-driven components
        self.relationship_analyzer = RelationshipAnalyzer()
        self.foreign_key_manager = ForeignKeyPoolManager(config)
        self.value_generator = DynamicValueGenerator()
        self.gx_extractor = gx_extractor

        self.logger = logging.getLogger(self.__class__.__name__)

    def pre_generate_key_pools(
        self,
        generators: "HealthcareDataGenerators",
        umf_files: dict[str, dict] | None = None,
        table_row_counts: dict[str, int] | None = None,
        cross_pipeline_seeds: dict[str, list[str]] | None = None,
    ) -> None:
        """Pre-generate relationship-aware pools of keys for consistent relationships.

        Args:
            generators: Healthcare data generators instance
            umf_files: Dictionary mapping table names to UMF metadata
            table_row_counts: Optional dict of table_name -> row_count for sizing pools
            cross_pipeline_seeds: Optional dict of column_name -> seed values from
                cross-pipeline FK references. Used to ensure FK pools contain values
                that exist in dependent pipeline tables.

        """
        self.logger.info(
            f"Pre-generating relationship-driven key pools (default size: {self.config.key_pool_size})"
        )

        if cross_pipeline_seeds:
            self.logger.info(
                f"Cross-pipeline seeds provided for columns: {list(cross_pipeline_seeds.keys())}"
            )

        if not umf_files:
            self.logger.warning(
                "No UMF files provided - skipping relationship-driven key pool generation"
            )
            return

        # Step 1: Analyze relationships to discover equivalence groups
        self.relationship_analyzer.analyze_umf_files(umf_files)
        equivalence_groups = self.relationship_analyzer.compute_equivalence_groups()

        self.logger.info(
            f"Discovered {len(equivalence_groups)} equivalence groups from UMF relationships"
        )

        # Step 2: Generate pools for each equivalence group
        for group_id, columns in equivalence_groups.items():
            self.logger.debug(
                f"Processing equivalence group '{group_id}' with columns: {columns}"
            )

            # Find a representative column to get metadata from
            representative_column = self._find_representative_column(columns, umf_files)
            if not representative_column:
                self.logger.warning(
                    f"No metadata found for equivalence group '{group_id}' - skipping"
                )
                continue

            # Create generator function for this column type
            # Note: Regex patterns are applied in _generate_column_value during table generation
            # Foreign key pools use sample_values from UMF metadata
            generator_func = self.value_generator.create_generator(
                representative_column
            )

            # Calculate pool size based on unique constraints
            pool_size = None
            if self.relationship_analyzer.group_contains_unique_constraint(columns):
                # Get all tables using these columns
                tables = self.relationship_analyzer.get_tables_for_columns(columns)

                # Calculate max row count across these tables
                if table_row_counts and tables:
                    max_rows = max(table_row_counts.get(table, 0) for table in tables)
                    pool_size = max_rows
                    constraint_cols = (
                        columns
                        & self.relationship_analyzer.get_unique_constraint_columns()
                    )
                    self.logger.info(
                        f"Group '{group_id}' contains unique constraint columns {constraint_cols}, "
                        + f"sizing pool to max table rows: {pool_size} (tables: {tables})"
                    )

            # Check if any column in this group has cross-pipeline seeds
            seed_values: list[str] | None = None
            if cross_pipeline_seeds:
                for col in columns:
                    if col in cross_pipeline_seeds:
                        seed_values = cross_pipeline_seeds[col]
                        self.logger.info(
                            f"Group '{group_id}' will use {len(seed_values)} cross-pipeline "
                            f"seed values from column '{col}'"
                        )
                        break

            # Generate pool for this equivalence group (with optional seeds)
            self.foreign_key_manager.generate_pool(
                group_id, columns, generator_func, pool_size, seed_values
            )

        self.logger.info(
            f"Successfully generated {len(equivalence_groups)} foreign key pools"
        )

    def _find_representative_column(
        self, columns: set[str], umf_files: dict[str, dict]
    ) -> dict[str, Any] | None:
        """Find a representative column from the equivalence group to get metadata.

        Prefers columns with sample_values defined for better pool generation.
        This ensures the FK pool generator uses a column that has proper sample data
        patterns rather than falling back to generic string generation.
        """
        candidates: list[tuple[bool, dict[str, Any]]] = []
        for table_data in umf_files.values():
            table_columns = table_data.get("columns", [])
            for col_def in table_columns:
                if col_def.get("name") in columns:
                    # Track whether this column has sample_values
                    has_samples = bool(col_def.get("sample_values"))
                    candidates.append((has_samples, col_def))

        if not candidates:
            return None

        # Sort to prefer columns with sample_values (True > False)
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # Obsolete methods removed - replaced by relationship-driven foreign key manager
    # All foreign key pool generation now handled by RelationshipAnalyzer,
    # ForeignKeyPoolManager, and DynamicValueGenerator from foreign_key_manager module

    def _create_weighted_distribution(self, pool_size: int) -> list[float]:
        """Create 80/20 weighted distribution for a pool."""
        high_freq_count = int(pool_size * 0.2)  # Top 20% of keys
        high_weight = self.config.high_frequency_key_ratio / high_freq_count
        low_weight = (1 - self.config.high_frequency_key_ratio) / (
            pool_size - high_freq_count
        )

        weights = []
        for i in range(pool_size):
            if i < high_freq_count:
                weights.append(high_weight)
            else:
                weights.append(low_weight)
        return weights

    def register_primary_key(self, table: str, key: str | float) -> None:
        """Register a primary key for reuse as foreign key."""
        self.primary_keys[table].append(key)

    def get_foreign_key(
        self, column_name: str, cardinality: str = "", mandatory: bool = False
    ) -> str | int | float | None:
        """Get foreign key from relationship-aware pools."""
        # Try to get value from foreign key manager first
        value = self.foreign_key_manager.get_value_for_column(column_name)

        if value is not None:
            # Track usage for one-to-one relationships
            if cardinality in ["one_to_one", "1:1"]:
                self.foreign_key_usage[str(value)] += 1
            return value

        # Fallback to primary keys if column not in any equivalence group
        # This handles cases where a column is used as FK but not part of discovered relationships
        for table_keys in self.primary_keys.values():
            if table_keys:
                key = random.choice(table_keys)
                if cardinality in ["one_to_one", "1:1"]:
                    self.foreign_key_usage[str(key)] += 1
                return key

        if mandatory:
            self.logger.warning(
                f"No foreign key available for mandatory column '{column_name}'"
            )

        return None

    def get_key_from_pool(self, key_type: str) -> str | int | float | None:
        """Get a key from a specific pool (used by data generators)."""
        return self.foreign_key_manager.get_value_for_column(key_type)


__all__ = ["KeyRegistry"]
