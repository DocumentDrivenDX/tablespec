"""Dynamic Foreign Key Pool Manager for relationship-driven synchronization.

This module provides components for analyzing relationships in UMF files and
generating synchronized foreign keys that enable proper joins in Phase 9.
"""

from collections import defaultdict
from collections.abc import Callable
import logging
from typing import Any


class RelationshipAnalyzer:
    """Analyzes UMF relationships to discover equivalence groups of foreign keys."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._relationships = []
        self._unique_constraint_columns: set[str] = set()
        self._column_to_tables: dict[str, set[str]] = defaultdict(set)

    def analyze_umf_files(self, umf_files: dict[str, dict[str, Any]]) -> None:
        """Extract all relationships and unique constraints from UMF files.

        Args:
            umf_files: Dictionary mapping table names to UMF metadata

        """
        self._relationships = []
        self._unique_constraint_columns = set()
        self._column_to_tables = defaultdict(set)

        for table_name, table_data in umf_files.items():
            relationships = table_data.get("relationships", {})

            # Extract outgoing relationships
            for rel in relationships.get("outgoing", []):
                source_col = rel["source_column"]
                self._relationships.append(
                    {
                        "source_table": table_name,
                        "source_column": source_col,
                        "target_table": rel["target_table"],
                        "target_column": rel["target_column"],
                    }
                )
                # Track which tables use each column
                self._column_to_tables[source_col].add(table_name)
                self._column_to_tables[rel["target_column"]].add(rel["target_table"])

            # Extract incoming relationships
            for rel in relationships.get("incoming", []):
                target_col = rel["target_column"]
                self._relationships.append(
                    {
                        "source_table": rel["source_table"],
                        "source_column": rel["source_column"],
                        "target_table": table_name,
                        "target_column": target_col,
                    }
                )
                # Track which tables use each column
                self._column_to_tables[rel["source_column"]].add(rel["source_table"])
                self._column_to_tables[target_col].add(table_name)

            # Extract foreign_keys relationships (alternative format used by some pipelines)
            for rel in relationships.get("foreign_keys", []):
                source_col = rel.get("column")
                target_table = rel.get("references_table")
                target_col = rel.get("references_column")
                if source_col and target_table and target_col:
                    self._relationships.append(
                        {
                            "source_table": table_name,
                            "source_column": source_col,
                            "target_table": target_table,
                            "target_column": target_col,
                        }
                    )
                    # Track which tables use each column
                    self._column_to_tables[source_col].add(table_name)
                    self._column_to_tables[target_col].add(target_table)

            # Extract unique constraints
            unique_constraints = table_data.get("unique_constraints", [])
            for constraint in unique_constraints:
                # Each constraint is a list of columns that together must be unique
                for column_name in constraint:
                    self._unique_constraint_columns.add(column_name)

    def compute_equivalence_groups(self) -> dict[str, set[str]]:
        """Compute equivalence groups using Union-Find algorithm.

        Returns:
            Dictionary mapping group IDs to sets of equivalent column names

        """
        if not self._relationships:
            return {}

        # Build graph of connected columns
        graph = defaultdict(set)
        all_columns = set()

        for rel in self._relationships:
            source_col = rel["source_column"]
            target_col = rel["target_column"]

            graph[source_col].add(target_col)
            graph[target_col].add(source_col)
            all_columns.add(source_col)
            all_columns.add(target_col)

        # Find connected components using DFS
        visited = set()
        groups = {}
        group_counter = 0

        for column in all_columns:
            if column not in visited:
                # Start new group
                group_id = f"group_{group_counter}"
                group_counter += 1
                current_group = set()

                # DFS to find all connected columns
                stack = [column]
                while stack:
                    current = stack.pop()
                    if current not in visited:
                        visited.add(current)
                        current_group.add(current)

                        # Add all connected columns to stack
                        for neighbor in graph[current]:
                            if neighbor not in visited:
                                stack.append(neighbor)

                groups[group_id] = current_group

        return groups

    def group_contains_unique_constraint(self, columns: set[str]) -> bool:
        """Check if any column in the group is part of a unique constraint.

        Args:
            columns: Set of column names in an equivalence group

        Returns:
            True if any column is in a unique constraint

        """
        return bool(columns & self._unique_constraint_columns)

    def get_tables_for_columns(self, columns: set[str]) -> set[str]:
        """Get all tables that use any of the given columns.

        Args:
            columns: Set of column names

        Returns:
            Set of table names that use these columns

        """
        tables = set()
        for column in columns:
            tables.update(self._column_to_tables.get(column, set()))
        return tables

    def get_unique_constraint_columns(self) -> set[str]:
        """Get all columns that are part of unique constraints.

        Returns:
            Set of column names in unique constraints

        """
        return self._unique_constraint_columns


class ForeignKeyPoolManager:
    """Manages shared foreign key pools for equivalence groups."""

    def __init__(self, config) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.pools = {}  # group_id -> list of values
        self._column_to_group = {}  # column_name -> group_id (exact match)
        self._normalized_to_group = {}  # normalized_column_name -> group_id (fuzzy match)
        # Per-record value tracking: ensures columns from the same equivalence group
        # get the same value within a single record (important for lookup tables)
        self._current_record_values: dict[str, Any] = {}

    def start_new_record(self) -> None:
        """Reset per-record value tracking for a new record.

        Call this at the start of each record generation to ensure columns
        from the same equivalence group get fresh values for each record,
        while still being consistent within the same record.
        """
        self._current_record_values = {}

    @staticmethod
    def _normalize_column_name(name: str) -> str:
        """Normalize column names for fuzzy matching.

        Converts to lowercase and removes underscores and spaces to match
        related columns with different naming conventions (e.g., ClientMemberId
        vs CLIENT_MEMBER_ID).

        Args:
            name: Original column name

        Returns:
            Normalized column name for matching

        """
        return name.lower().replace("_", "").replace(" ", "")

    def generate_pool(
        self,
        group_id: str,
        columns: set[str],
        generator_func: Callable,
        pool_size: int | None = None,
        seed_values: list[str] | None = None,
    ) -> None:
        """Generate a shared pool of values for an equivalence group.

        Args:
            group_id: Unique identifier for the equivalence group
            columns: Set of column names in this group
            generator_func: Function that generates a single value
            pool_size: Optional custom pool size; defaults to config.key_pool_size
            seed_values: Optional list of seed values to pre-populate the pool.
                These values come from cross-pipeline FK references and ensure
                that generated data will match existing values in dependent tables.

        """
        # Use custom pool size if provided, otherwise use config default
        size = pool_size if pool_size is not None else self.config.key_pool_size

        # Start with seed values if provided (for cross-pipeline FK coordination)
        pool_values = []
        seen_values = set()

        if seed_values:
            for value in seed_values:
                if value not in seen_values:
                    pool_values.append(value)
                    seen_values.add(value)
            self.logger.info(
                f"Pool '{group_id}' seeded with {len(pool_values)} cross-pipeline values"
            )

        # Generate additional values to fill pool if needed
        attempts = 0
        max_attempts = size * 10  # Allow 10x attempts to find unique values

        while len(pool_values) < size and attempts < max_attempts:
            value = generator_func()
            attempts += 1

            # Only add if unique
            if value not in seen_values:
                pool_values.append(value)
                seen_values.add(value)

        if len(pool_values) < size:
            self.logger.warning(
                f"Could only generate {len(pool_values)} unique values for pool '{group_id}' "
                + f"(requested {size}) after {max_attempts} attempts"
            )

        self.pools[group_id] = pool_values

        # Map all columns to this group (exact and normalized)
        for column in columns:
            # Store exact match for performance
            self._column_to_group[column] = group_id
            # Store normalized match for cross-table foreign keys
            normalized = self._normalize_column_name(column)
            self._normalized_to_group[normalized] = group_id

        self.logger.info(
            f"Generated pool '{group_id}' with {len(pool_values)} unique values for columns: {columns}"
        )

    def get_value_for_column(self, column_name: str) -> Any:
        """Get a value from the pool for the given column.

        Tries exact match first, then falls back to normalized name matching
        to handle columns with different naming conventions (e.g., ClientMemberId
        vs CLIENT_MEMBER_ID).

        Uses per-record value tracking to ensure that multiple columns from the
        same equivalence group within the same record get the SAME value. This is
        critical for lookup tables like datawarehouse where member_id and
        insurance_policy must be coordinated.

        Args:
            column_name: Name of the column needing a value

        Returns:
            A value from the appropriate pool, or None if column not found

        """
        import random

        # Try exact match first (fast path)
        group_id = self._column_to_group.get(column_name)

        # Fallback to normalized match for cross-table foreign keys
        if not group_id:
            normalized = self._normalize_column_name(column_name)
            group_id = self._normalized_to_group.get(normalized)

        if not group_id or group_id not in self.pools:
            return None

        pool = self.pools[group_id]
        if not pool:
            return None

        # Check if we already have a value for this equivalence group in the current record
        # This ensures columns like member_id and insurance_policy in the same row get the same value
        if group_id in self._current_record_values:
            return self._current_record_values[group_id]

        # Select a new value for this group
        if self.config.key_distribution_80_20:
            # Top 20% of keys get 80% of selections
            high_freq_count = max(1, len(pool) // 5)  # Top 20%

            if random.random() < self.config.high_frequency_key_ratio:
                # Select from high-frequency keys (top 20%)
                value = random.choice(pool[:high_freq_count])
            else:
                # Select from remaining keys
                value = random.choice(
                    pool[high_freq_count:] if high_freq_count < len(pool) else pool
                )
        else:
            # Uniform distribution
            value = random.choice(pool)

        # Cache the value for this group for the current record
        self._current_record_values[group_id] = value
        return value

    def get_columns_for_group(self, group_id: str) -> list[str]:
        """Get all column names that belong to a given equivalence group.

        Args:
            group_id: The equivalence group identifier

        Returns:
            List of column names in this group

        """
        return [col for col, gid in self._column_to_group.items() if gid == group_id]


class DynamicValueGenerator:
    """Generates values dynamically based on UMF metadata."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def create_generator(self, column_metadata: dict[str, Any]) -> Callable:
        """Create a generator function based on column metadata.

        Args:
            column_metadata: UMF column metadata with data_type, sample_values, etc.

        Returns:
            Function that generates values matching the column's characteristics

        """
        data_type = (column_metadata.get("data_type") or "STRING").upper()
        sample_values = column_metadata.get("sample_values", []) or []
        column_metadata.get("name", "unknown")

        if sample_values:
            return self._create_sample_based_generator(sample_values, data_type)
        if data_type == "INTEGER":
            return self._create_integer_generator(column_metadata)
        return self._create_string_generator(column_metadata)

    def _create_sample_based_generator(
        self, sample_values: list, data_type: str
    ) -> Callable:
        """Create generator that mimics sample values."""
        import random

        def generator():
            # Filter out obvious column names and placeholders
            valid_samples = [
                s for s in sample_values if not self._is_column_name_or_placeholder(s)
            ]

            if not valid_samples:
                # Fallback to pattern-based generation
                return self._generate_fallback_pattern(sample_values, data_type)

            # Analyze sample patterns for string-like types
            # Note: UMF uses "StringType" so we need to check for that too
            string_like_types = {"STRING", "STRINGTYPE", "TEXT", "CHAR"}
            uppercase_type = data_type.upper()
            if uppercase_type in string_like_types and valid_samples:
                sample = random.choice(valid_samples)
                if sample.isdigit():
                    # Generate similar numeric string
                    length = len(sample)
                    return "".join(str(random.randint(0, 9)) for _ in range(length))
                if self._looks_like_member_id(sample):
                    # Generate member ID pattern: 2 letters + 11 digits
                    return self._generate_member_id_pattern(sample)
                # For other patterns, return one of the valid samples
                return sample
            return random.choice(valid_samples)

        return generator

    def _is_column_name_or_placeholder(self, value: str) -> bool:
        """Check if a value looks like a column name or placeholder."""
        if not value or len(value.strip()) == 0:
            return True

        # Common patterns that indicate column names or placeholders
        suspicious_patterns = [
            "CLIENTMEMBERID",
            "CLIENT_MEMBER_ID",
            "ClientMemberId",
            "CLIENT MBRID",
            "MEMBER_ID",
            "MemberId",
            "memberid",
            "client_id",
            "F",
            "O",
            "R",
            "GovtID",
            "MemberLastName",
            "MemberFirstName",
            "MemberMiddleName",
        ]

        # Check for exact matches or very short values
        if value in suspicious_patterns or len(value) <= 2:
            return True

        # Check for patterns that look like column descriptions
        return bool(
            any(
                word in value.upper()
                for word in ["MEMBER", "CLIENT", "ID", "NAME", "FIRST", "LAST"]
            )
            and (len(value.split()) > 1 or "_" in value)
        )

    def _looks_like_member_id(self, value: str) -> bool:
        """Check if a value looks like a real member ID."""
        if len(value) < 5:
            return False

        # Pattern: starts with letters, followed by digits (like AL98765432101)
        if len(value) >= 10 and value[:2].isalpha() and value[2:].isdigit():
            return True

        # Other alphanumeric patterns that could be member IDs
        return bool(any(c.isdigit() for c in value) and any(c.isalpha() for c in value))

    def _generate_member_id_pattern(self, sample: str) -> str:
        """Generate a member ID following the pattern of the sample."""
        import random
        import string

        # Default pattern: 2 letters + 11 digits (like AL98765432101)
        if len(sample) >= 10 and sample[:2].isalpha() and sample[2:].isdigit():
            prefix = "".join(random.choice(string.ascii_uppercase) for _ in range(2))
            suffix = "".join(str(random.randint(0, 9)) for _ in range(len(sample) - 2))
            return f"{prefix}{suffix}"

        # Fallback: generate alphanumeric ID of similar length
        length = len(sample)
        chars = string.ascii_uppercase + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    def _generate_fallback_pattern(self, sample_values: list, data_type: str) -> str:
        """Generate a fallback pattern when no valid samples are found."""
        import random
        import string

        if data_type.upper() in {"STRING", "TEXT", "CHAR"}:
            # Generate a reasonable member ID pattern
            prefix = "".join(random.choice(string.ascii_uppercase) for _ in range(2))
            suffix = "".join(str(random.randint(0, 9)) for _ in range(11))
            return f"{prefix}{suffix}"

        # For other types, generate something reasonable
        return "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(10)
        )

    def _create_integer_generator(self, metadata: dict[str, Any]) -> Callable:
        """Create integer generator based on metadata."""
        import random

        # Check description for hints about range
        description = metadata.get("description", "").lower()

        def generator():
            if "rank" in description and "1-6" in description:
                # Handle tier ranks - mostly 1-6, some higher for passive
                if random.random() < 0.8:
                    return random.randint(1, 6)
                return random.randint(7, 120)  # Passive outreach values
            # Generic integer
            return random.randint(1, 1000)

        return generator

    def _create_string_generator(self, metadata: dict[str, Any]) -> Callable:
        """Create string generator with reasonable defaults."""
        import random
        import string

        length = metadata.get("length", 10)

        def generator():
            # Generate alphanumeric string
            chars = string.ascii_letters + string.digits
            return "".join(random.choice(chars) for _ in range(min(length, 10)))

        return generator
