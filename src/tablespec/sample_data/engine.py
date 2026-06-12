"""Main sample data generation engine."""

import csv
import json
import logging
from pathlib import Path
import random
import re
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

from tablespec import GXConstraintExtractor
from tablespec.expectation_utils import expectation_dicts_from_umf_data

try:
    from tablespec.inference.domain_types import DomainTypeRegistry
except ImportError:
    DomainTypeRegistry = None  # type: ignore[assignment,misc]

try:
    from tablespec.ingestion import PROVENANCE_COLUMNS
except ImportError:
    # ingestion module not yet ported; define an empty fallback
    PROVENANCE_COLUMNS: dict[str, Any] = {}  # type: ignore[no-redef]

from tablespec.naming import position_sort_key
from tablespec.umf_loader import UMFLoader

from .column_value_generator import ColumnValueGenerator
from .config import GenerationConfig
from .constraint_handlers import ConstraintHandlers
from .date_processing import convert_umf_format_to_strftime, extract_date_constraints
from .filename_generator import FilenameGenerator
from .generators import HealthcareDataGenerators
from .graph import RelationshipGraph
from .registry import KeyRegistry
from .validation import ValidationRuleProcessor

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


class CrossPipelineFK(NamedTuple):
    """Represents a cross-pipeline foreign key reference."""

    column: str
    references_pipeline: str
    references_table: str
    references_column: str


class TableGenerationInfo(TypedDict):
    """Information about a generated table."""

    record_count: int
    columns: list[str]
    column_count: int


class GenerationConfigDict(TypedDict):
    """Configuration section in generation report."""

    num_members: int
    relationship_density: float
    temporal_range_days: int


class KeyStatistics(TypedDict):
    """Key statistics from generation."""

    total_tables: int
    total_records: int
    unique_member_ids: int


class GenerationReport(TypedDict):
    """Summary report of data generation."""

    generation_timestamp: str
    configuration: GenerationConfigDict
    tables_generated: dict[str, TableGenerationInfo]
    key_statistics: KeyStatistics


def _get_effective_position(col: dict[str, Any]) -> str | None:
    """Get the effective position for a column, checking position field and aliases.

    Position is used to determine the correct column order in generated sample data files.
    This ensures columns are written in the order expected by downstream file readers.

    Priority:
    1. Explicit 'position' field (e.g., "A", "B", "1", "2")
    2. First Excel column letter alias (single capital letter A-Z or double AA-ZZ)
    3. None if no position information available

    Args:
        col: Column definition dict from UMF

    Returns:
        Position string or None if no position info available

    """
    # Check explicit position field first
    if col.get("position"):
        return col["position"]

    # Check aliases for Excel column letter patterns
    aliases = col.get("aliases") or []
    for alias in aliases:
        # Match Excel column patterns: A-Z or AA-ZZ
        if isinstance(alias, str) and re.match(r"^[A-Z]{1,2}$", alias):
            return alias

    return None


class SampleDataGenerator:
    """Main sample data generation engine."""

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        config: GenerationConfig,
        spark: "SparkSession | None" = None,
    ) -> None:
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.config = config
        self.spark = spark  # Optional Spark session for cross-pipeline FK seeding
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize components in correct order
        self.gx_extractor = GXConstraintExtractor()
        self.domain_type_registry = (
            DomainTypeRegistry() if DomainTypeRegistry is not None else None
        )
        self.key_registry = KeyRegistry(config, self.gx_extractor)
        self.generators = HealthcareDataGenerators(config, self.key_registry)
        self.validation_processor = ValidationRuleProcessor(self.generators)
        self.constraint_handlers = ConstraintHandlers()
        self.graph = RelationshipGraph()
        self.generated_data: dict[str, list[dict]] = {}
        self.gx_expectations_cache: dict[
            str, dict[str, Any]
        ] = {}  # Cache loaded expectations
        self.debug_logged_columns: set[tuple[str, str]] = (
            set()
        )  # Track (table, column) debug logs
        self.column_value_generator = ColumnValueGenerator(
            gx_extractor=self.gx_extractor,
            domain_type_registry=self.domain_type_registry,
            generators=self.generators,
            key_registry=self.key_registry,
            constraint_handlers=self.constraint_handlers,
            config=self.config,
            debug_logged_columns=self.debug_logged_columns,
        )
        self.filename_generator = FilenameGenerator(self.logger)
        self._generated_filenames: dict[
            str, str
        ] = {}  # filename -> table_name that wrote it

    def load_umf_files(self) -> dict[str, dict]:
        """Load all UMF files from input directory using standard UMF discovery.

        Uses UMFLoader to load from split format directories or JSON tablespecs.
        Supports both formats automatically via UMFLoader format detection.
        """
        umf_files = {}
        converter = UMFLoader()

        # Look for tables in multiple locations (for flexibility)
        possible_dirs = [
            self.input_dir / "tables",  # Standard location: input_dir/tables/
            self.input_dir,  # Fallback: tables directly in input_dir
        ]

        tables_dir = None
        for candidate in possible_dirs:
            if candidate.exists():
                tables_dir = candidate
                break

        if tables_dir is None:
            self.logger.warning(f"No tables directory found in {self.input_dir}")
            return umf_files

        # Load tables using UMFLoader (supports both split format and JSON)
        for item in sorted(tables_dir.iterdir()):
            # Skip hidden files, __pycache__, and non-table items
            if item.name.startswith(".") or item.name.startswith("__"):
                continue

            # Try to load: UMFLoader auto-detects format (split dir or JSON file)
            try:
                # Load via UMFLoader - works for directories (split) and JSON files
                umf = converter.load(item)
                table_name = umf.table_name
                # Convert UMF model to dict for compatibility with rest of code
                umf_files[table_name] = umf.model_dump(mode="json", exclude_none=True)
                format_type = "directory" if item.is_dir() else "JSON file"
                self.logger.debug(
                    f"Loaded UMF for {table_name} from {format_type}: {item.name}"
                )
            except (ValueError, FileNotFoundError):
                # Not a valid UMF file/directory - skip silently
                continue
            except Exception as e:
                self.logger.warning(f"Failed to load UMF from {item.name}: {e}")
                # Continue loading other tables instead of failing completely
                continue

        self.logger.info(f"Loaded {len(umf_files)} UMF files from {tables_dir}")
        return umf_files

    def build_relationship_graph(self, umf_files: dict[str, dict]) -> None:
        """Build relationship graph from UMF relationship data."""
        # Filter out generated tables (they use survivorship, not dependency ordering)
        filtered_tables = {
            name: data
            for name, data in umf_files.items()
            if data.get("table_type") != "generated"
        }

        excluded_count = len(umf_files) - len(filtered_tables)
        if excluded_count > 0:
            excluded_names = [
                name
                for name, data in umf_files.items()
                if data.get("table_type") == "generated"
            ]
            self.logger.info(
                f"Excluded {excluded_count} generated tables from dependency graph: {excluded_names}"
            )

        # Add filtered tables to graph
        for table_name, umf_data in filtered_tables.items():
            self.graph.add_table(table_name, umf_data)

        # Add relationships (only for filtered tables)
        for table_name, umf_data in filtered_tables.items():
            if "relationships" in umf_data and "incoming" in umf_data["relationships"]:
                # Process incoming relationships (this table depends on others)
                for rel in umf_data["relationships"]["incoming"]:
                    source_table = rel.get("source_table")
                    # Only add relationship if source is also not generated
                    if source_table and source_table in filtered_tables:
                        self.graph.add_relationship(source_table, table_name)

        self.logger.info(
            f"Built relationship graph with {len(self.graph.nodes)} tables (excluded {excluded_count} generated)"
        )

    def _discover_cross_pipeline_fks(
        self, umf_files: dict[str, dict]
    ) -> dict[str, CrossPipelineFK]:
        """Find all cross_pipeline: true foreign keys in UMF metadata.

        Scans all tables' foreign_keys relationships for cross-pipeline references.
        These are used to seed FK pools with values from dependent pipelines.

        Args:
            umf_files: Dictionary mapping table names to UMF metadata

        Returns:
            Dictionary mapping column names to CrossPipelineFK details

        """
        cross_fks: dict[str, CrossPipelineFK] = {}

        for table_name, umf_data in umf_files.items():
            relationships = umf_data.get("relationships", {})
            foreign_keys = relationships.get("foreign_keys", [])

            for fk in foreign_keys:
                # Only process cross-pipeline FKs
                if not fk.get("cross_pipeline"):
                    continue

                column = fk.get("column")
                refs_pipeline = fk.get("references_pipeline")
                refs_table = fk.get("references_table")
                refs_column = fk.get("references_column", column)

                if column and refs_pipeline and refs_table:
                    cross_fks[column] = CrossPipelineFK(
                        column=column,
                        references_pipeline=refs_pipeline,
                        references_table=refs_table,
                        references_column=refs_column,
                    )
                    self.logger.debug(
                        f"Found cross-pipeline FK: {table_name}.{column} -> "
                        f"{refs_pipeline}.{refs_table}.{refs_column}"
                    )

        if cross_fks:
            self.logger.info(
                f"Discovered {len(cross_fks)} cross-pipeline FK(s): {list(cross_fks.keys())}"
            )

        return cross_fks

    def _load_cross_pipeline_seeds(
        self, cross_fks: dict[str, CrossPipelineFK]
    ) -> dict[str, list[str]]:
        """Query Unity Catalog Gold tables for existing primary key values.

        For each cross-pipeline FK, reads the referenced table's PK column
        from the Gold layer to get existing values. These values are used
        to seed FK pools so that cross-pipeline JOINs will match.

        Args:
            cross_fks: Dictionary of cross-pipeline FK definitions

        Returns:
            Dictionary mapping column names to lists of seed values

        """
        seeds: dict[str, list[str]] = {}

        if not self.spark:
            self.logger.debug("No Spark session - skipping cross-pipeline FK seeding")
            return seeds

        if not cross_fks:
            return seeds

        for column, fk in cross_fks.items():
            # Try to read from Gold table in Unity Catalog
            # Format: local_cha_gold.{pipeline}.{table}
            table_path = (
                f"local_cha_gold.{fk.references_pipeline}.{fk.references_table}"
            )

            try:
                df = self.spark.table(table_path)
                # Get distinct values from the referenced column
                values = [
                    str(row[0])
                    for row in df.select(fk.references_column).distinct().collect()
                    if row[0] is not None
                ]

                if values:
                    seeds[column] = values
                    self.logger.info(
                        f"Loaded {len(values)} seed values for {column} "
                        f"from {table_path}.{fk.references_column}"
                    )
                else:
                    self.logger.warning(
                        f"No values found in {table_path}.{fk.references_column} for seeding"
                    )

            except Exception as e:
                # Table doesn't exist yet or other error - use normal generation
                self.logger.debug(
                    f"Could not load cross-pipeline seeds from {table_path}: {e}"
                )

        return seeds

    def generate_table_data(
        self, table_name: str, umf_data: dict[str, Any], num_records: int
    ) -> list[dict]:
        """Generate sample data for a single table."""
        self.logger.info(f"Generating {num_records} records for {table_name}")

        # Load GX expectations for this table from UMF (cached)
        if table_name not in self.gx_expectations_cache:
            expectations_list = expectation_dicts_from_umf_data(umf_data)

            if expectations_list:
                # Create GX suite dict format for compatibility with extractor
                gx_expectations = {
                    "name": f"{table_name}_suite",
                    "expectations": expectations_list,
                }
                self.logger.info(
                    f"Loaded GX expectations for {table_name} from UMF: {len(expectations_list)} expectations"
                )
            else:
                # No expectations in UMF
                gx_expectations = None
                self.logger.warning(f"No GX expectations found in UMF for {table_name}")

            if gx_expectations is not None:
                self.gx_expectations_cache[table_name] = gx_expectations
            else:
                self.gx_expectations_cache[table_name] = {}

            if gx_expectations:
                value_sets = self.gx_extractor.extract_value_sets(gx_expectations)
                self.logger.info(
                    f"Extracted constraints from GX expectations for {table_name}: "
                    + f"{len(value_sets)} value_set constraints"
                )

        columns = umf_data.get("columns", [])
        records = []

        # Track unique values for primary/unique key columns to ensure uniqueness
        unique_value_trackers: dict[str, set] = {}

        # Track composite primary key combinations for uniqueness
        primary_key = umf_data.get("primary_key", [])
        composite_pk_tracker: set[tuple] = set()

        # Track filename-sourced column values (constant per file, not per row)
        filename_column_values: dict[str, Any] = {}

        # Extract filename pattern for validation
        file_format = umf_data.get("file_format", {})
        filename_pattern_field = file_format.get("filename_pattern")

        # Handle both flat and nested structures
        if isinstance(filename_pattern_field, dict):
            filename_pattern_regex = filename_pattern_field.get("regex")
            captures = filename_pattern_field.get("captures", {})
        else:
            filename_pattern_regex = filename_pattern_field
            captures = file_format.get("captures", {})

        for col in columns:
            if col.get("source") == "filename":
                col_name = col["name"]
                sample_values = col.get("sample_values", [])
                if sample_values and len(sample_values) > 0:
                    # Validate sample_values against filename pattern regex if available
                    validated_values = sample_values
                    if filename_pattern_regex and captures:
                        # Find which capture group this column corresponds to
                        capture_group_pattern = (
                            self._get_capture_group_pattern_for_column(
                                col_name, captures, filename_pattern_regex
                            )
                        )
                        if capture_group_pattern:
                            # Filter sample_values to only those matching the capture group pattern
                            # Use case-insensitive matching for flexibility
                            validated_values = [
                                v
                                for v in sample_values
                                if re.fullmatch(
                                    capture_group_pattern, str(v), re.IGNORECASE
                                )
                            ]
                            if not validated_values:
                                self.logger.warning(
                                    f"{table_name}.{col_name}: None of the sample_values {sample_values} "
                                    + f"match the filename pattern capture group /{capture_group_pattern}/. "
                                    + "Using unvalidated sample_values."
                                )
                                validated_values = sample_values
                            elif len(validated_values) < len(sample_values):
                                excluded = set(sample_values) - set(validated_values)
                                self.logger.info(
                                    f"{table_name}.{col_name}: Excluded {len(excluded)} sample_values "
                                    + f"that don't match pattern /{capture_group_pattern}/: {excluded}"
                                )

                    # Pick ONE value for this column for the entire file
                    filename_column_values[col_name] = random.choice(validated_values)
                    self.logger.debug(
                        f"Filename column {col_name} will use constant value: {filename_column_values[col_name]}"
                    )

        # Extract multi-column constraints from GX expectations
        gx_expectations = self.gx_expectations_cache.get(table_name)
        column_equality_constraints: dict[str, list[dict[str, str]]] = {}
        unique_within_record_constraints: list[dict[str, Any]] = []

        if gx_expectations:
            column_equality_constraints = (
                self.gx_extractor.extract_column_pair_equality_constraints(
                    gx_expectations
                )
            )
            unique_within_record_constraints = (
                self.gx_extractor.extract_unique_within_record_constraints(
                    gx_expectations
                )
            )

            if column_equality_constraints:
                self.logger.debug(
                    f"Found {len(column_equality_constraints)} column equality constraints for {table_name}"
                )
            if unique_within_record_constraints:
                self.logger.debug(
                    f"Found {len(unique_within_record_constraints)} unique-within-record constraints for {table_name}"
                )

        # Build forced records from sample_data_cases in UMF (generic approach)
        sample_data_cases = umf_data.get("sample_data_cases", [])
        if sample_data_cases:
            forced_records = self._build_forced_records_from_cases(
                table_name,
                sample_data_cases,
                columns,
                umf_data,
                unique_value_trackers,
                column_equality_constraints,
                unique_within_record_constraints,
                filename_column_values,
            )
            for record in forced_records:
                if len(primary_key) > 1:
                    composite_pk_tracker.add(
                        tuple(record.get(pk_col) for pk_col in primary_key)
                    )
            records.extend(forced_records)
            num_records = max(0, num_records - len(forced_records))

        for _ in range(num_records):
            max_composite_pk_attempts = 500
            composite_pk_attempt = 0

            while composite_pk_attempt < max_composite_pk_attempts:
                record = {}

                # Reset per-record foreign key tracking so columns from the same
                # equivalence group get the same value within this record
                self.key_registry.foreign_key_manager.start_new_record()

                for col in columns:
                    col_name = col["name"]
                    col_type = col.get("data_type", "STRING")
                    nullable = col.get("nullable", {})
                    sample_values = col.get("sample_values", [])
                    col.get("key_type")  # NEW: Get key_type from UMF
                    source = col.get("source", "data")

                    # Skip derived columns - they're computed at runtime in Silver/Gold layers
                    if source == "derived":
                        continue

                    # Check if should be null based on configuration
                    null_pct = self.config.null_percentage.get(col_name, 0.0)
                    if random.random() < null_pct and any(nullable.values()):
                        record[col_name] = None
                        continue

                    # Generate value based on column metadata
                    record[col_name] = self._generate_column_value(
                        table_name,
                        col,
                        col_type,
                        sample_values,
                        umf_data,
                        unique_value_trackers,
                        record,
                        column_equality_constraints,
                        unique_within_record_constraints,
                        filename_column_values,
                    )

                # Check composite primary key uniqueness if applicable
                if len(primary_key) > 1:
                    # Extract composite key values
                    composite_key_values = tuple(
                        record.get(pk_col) for pk_col in primary_key
                    )

                    # Check if this combination already exists
                    if composite_key_values in composite_pk_tracker:
                        composite_pk_attempt += 1

                        # After 50 attempts, start adding suffixes to diversify values
                        if composite_pk_attempt >= 50:
                            # Find a non-FK PK column to add suffix to (prefer non-member_id columns)
                            suffix_col = None
                            for pk_col in primary_key:
                                col_meta = next(
                                    (c for c in columns if c["name"] == pk_col), None
                                )
                                if col_meta:
                                    # Skip FK columns and member_id columns
                                    key_type = col_meta.get("key_type", "")
                                    if (
                                        "foreign" not in str(key_type).lower()
                                        and "member_id" not in pk_col.lower()
                                    ):
                                        suffix_col = pk_col
                                        break
                            # Fallback to first non-FK column if no suitable column found
                            if suffix_col is None:
                                for pk_col in primary_key:
                                    col_meta = next(
                                        (c for c in columns if c["name"] == pk_col),
                                        None,
                                    )
                                    if (
                                        col_meta
                                        and "foreign"
                                        not in str(col_meta.get("key_type", "")).lower()
                                    ):
                                        suffix_col = pk_col
                                        break

                            if suffix_col and record.get(suffix_col) is not None:
                                # Add suffix to make combination unique
                                original_val = record[suffix_col]
                                suffix_num = composite_pk_attempt - 49
                                if isinstance(original_val, str):
                                    # Strip any existing suffix and add new one
                                    base_val = (
                                        original_val.rsplit("_", 1)[0]
                                        if "_" in original_val
                                        else original_val
                                    )
                                    record[suffix_col] = f"{base_val}_{suffix_num}"
                                else:
                                    record[suffix_col] = f"{original_val}_{suffix_num}"
                                # Re-extract composite key with modified value
                                composite_key_values = tuple(
                                    record.get(pk_col) for pk_col in primary_key
                                )
                                # If still duplicate, continue retrying
                                if composite_key_values in composite_pk_tracker:
                                    if composite_pk_attempt < max_composite_pk_attempts:
                                        continue
                                else:
                                    # Success! Track and break
                                    composite_pk_tracker.add(composite_key_values)
                                    break

                        if composite_pk_attempt < max_composite_pk_attempts:
                            # Clear the unique value trackers for PK columns to allow regeneration
                            for pk_col in primary_key:
                                if pk_col in unique_value_trackers:
                                    # Remove the just-generated value from the tracker
                                    pk_value = record.get(pk_col)
                                    if (
                                        pk_value is not None
                                        and pk_value in unique_value_trackers[pk_col]
                                    ):
                                        unique_value_trackers[pk_col].remove(pk_value)
                            continue  # Retry with new values
                        self.logger.error(
                            f"Failed to generate unique composite primary key for {table_name} "
                            f"after {max_composite_pk_attempts} attempts. PK columns: {primary_key}"
                        )
                        msg = f"Could not generate unique composite primary key for {table_name}"
                        raise ValueError(msg)
                    # Unique combination found, track it
                    composite_pk_tracker.add(composite_key_values)
                    break  # Exit retry loop
                # No composite PK, accept record immediately
                break

            records.append(record)

        # Register primary keys for foreign key relationships
        if primary_key:
            for record in records:
                # For compound keys, create a composite key value
                if len(primary_key) == 1:
                    key_value = record.get(primary_key[0])
                    if key_value is not None:
                        self.key_registry.register_primary_key(table_name, key_value)
                else:
                    # For compound keys, register the first data column (skip filename columns)
                    for pk_col in primary_key:
                        col_meta = next(
                            (c for c in columns if c["name"] == pk_col), None
                        )
                        if col_meta and col_meta.get("source") == "data":
                            key_value = record.get(pk_col)
                            if key_value is not None:
                                self.key_registry.register_primary_key(
                                    table_name, key_value
                                )
                            break

        return records

    def _build_forced_records_from_cases(
        self,
        table_name: str,
        sample_data_cases: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        umf_data: dict[str, Any],
        unique_value_trackers: dict[str, set],
        column_equality_constraints: dict[str, list[dict[str, str]]],
        unique_within_record_constraints: list[dict[str, Any]],
        filename_column_values: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build forced records from sample_data_cases defined in UMF.

        This generic method reads sample_data_cases from the UMF specification and
        creates records with the specified column values, generating random values
        for unspecified columns.

        Args:
            table_name: Name of the table being generated
            sample_data_cases: List of dicts defining forced column values
            columns: Column definitions from UMF
            umf_data: Full UMF data dictionary
            unique_value_trackers: Trackers for unique value constraints
            column_equality_constraints: Cross-column equality constraints
            unique_within_record_constraints: Within-record uniqueness constraints
            filename_column_values: Values derived from filename patterns

        Returns:
            List of forced record dictionaries

        """
        forced_records = []

        for case in sample_data_cases:
            record: dict[str, Any] = {}
            self.key_registry.foreign_key_manager.start_new_record()
            for col in columns:
                col_name = col["name"]
                col_type = col.get("data_type", "STRING")
                sample_values = col.get("sample_values", [])
                source = col.get("source", "data")

                if source == "derived":
                    continue

                if col_name in case:
                    record[col_name] = case[col_name]
                    # Track forced values in unique_value_trackers to prevent
                    # random records from generating duplicate PK/unique values
                    key_type = col.get("key_type")
                    if key_type in ("primary", "unique", "foreign_one_to_one"):
                        if col_name not in unique_value_trackers:
                            unique_value_trackers[col_name] = set()
                        unique_value_trackers[col_name].add(case[col_name])
                    continue

                record[col_name] = self._generate_column_value(
                    table_name,
                    col,
                    col_type,
                    sample_values,
                    umf_data,
                    unique_value_trackers,
                    record,
                    column_equality_constraints,
                    unique_within_record_constraints,
                    filename_column_values,
                )
            forced_records.append(record)

        return forced_records

    def _get_column_validation_rules(
        self, col_name: str, umf_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract validation rules for a specific column from UMF data."""
        # Look for validation rules in column definition
        for column in umf_data.get("columns", []):
            if column.get("name") == col_name:
                return column.get("validation_rules")
        return None

    def _extract_date_constraints(
        self, col_name: str, umf_data: dict[str, Any]
    ) -> dict[str, str] | None:
        """Extract min/max date constraints from validation expectations.

        Delegates to date_processing.extract_date_constraints().

        Args:
            col_name: Name of the column
            umf_data: UMF data dictionary

        Returns:
            Dictionary with min_value and/or max_value keys if found, else None

        """
        return extract_date_constraints(col_name, umf_data)

    def _get_capture_group_pattern_for_column(
        self, col_name: str, captures: dict[str, Any], filename_pattern: str
    ) -> str | None:
        """Extract the regex pattern for a specific column's capture group.

        Delegates to filename_generator.get_capture_group_pattern_for_column().

        Args:
            col_name: Column name to find pattern for
            captures: Capture group mapping (e.g., {"1": "source_vendor_prefix", "2": "source_file_date"})
            filename_pattern: Full filename regex pattern

        Returns:
            Regex pattern for the capture group, or None if not found

        """
        return self.filename_generator.get_capture_group_pattern_for_column(
            col_name, captures, filename_pattern
        )

    def _convert_umf_format_to_strftime(self, umf_format: str | None) -> str | None:
        """Convert UMF date format specification to Python strftime format.

        Delegates to date_processing.convert_umf_format_to_strftime().

        Args:
            umf_format: UMF date format string (e.g., "MM/DD/YYYY", "YYYY-MM-DD HH:mm:ss")

        Returns:
            Python strftime format string, or None if input is None/empty

        """
        return convert_umf_format_to_strftime(umf_format)

    def _generate_column_value(
        self,
        table_name: str,
        col: dict[str, Any],
        col_type: str,
        sample_values: list[str],
        umf_data: dict[str, Any],
        unique_value_trackers: dict[str, set],
        record: dict[str, Any],
        column_equality_constraints: dict[str, list[dict[str, str]]],
        unique_within_record_constraints: list[dict[str, Any]],
        filename_column_values: dict[str, Any],
    ) -> str | int | float | bool | list[float] | None:
        """Generate appropriate value for a specific column using UMF metadata.

        Delegates to ColumnValueGenerator for the actual value generation logic.

        Args:
            table_name: Name of the table
            col: Full column dictionary from UMF with key_type, source, etc.
            col_type: Column data type
            sample_values: Sample values from UMF
            umf_data: Full UMF data for relationship lookups
            unique_value_trackers: Dict tracking unique values for primary/unique keys
            record: Partially-built record (for multi-column constraint checking)
            column_equality_constraints: Dict of column equality constraints
            unique_within_record_constraints: List of unique-within-record constraints
            filename_column_values: Pre-selected constant values for filename-sourced columns

        Returns:
            Generated value for the column

        """
        return self.column_value_generator.generate_column_value(
            table_name=table_name,
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers=unique_value_trackers,
            record=record,
            column_equality_constraints=column_equality_constraints,
            unique_within_record_constraints=unique_within_record_constraints,
            filename_column_values=filename_column_values,
            gx_expectations_cache=self.gx_expectations_cache,
            should_apply_equality_constraint_fn=self._should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=self._should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=self._ensure_distinct_from_columns,
        )

    def _should_apply_equality_constraint(
        self,
        record: dict[str, Any],
        col_name: str,
        other_col: str,
        ignore_row_if: str,
    ) -> bool:
        """Check if equality constraint should be applied based on ignore_row_if logic.

        Delegates to constraint_handlers.should_apply_equality_constraint().

        Args:
            record: Current partially-built record
            col_name: Current column name (being generated, not yet in record)
            other_col: Other column in equality constraint (may already be in record)
            ignore_row_if: Ignore condition ('never', 'either_value_is_missing', 'both_values_are_missing')

        Returns:
            True if constraint should be applied, False otherwise

        """
        return self.constraint_handlers.should_apply_equality_constraint(
            record, col_name, other_col, ignore_row_if
        )

    def _should_apply_unique_within_record_constraint(
        self,
        record: dict[str, Any],
        constraint_columns: list[str],
        ignore_row_if: str,
    ) -> bool:
        """Check if unique-within-record constraint should be applied.

        Delegates to constraint_handlers.should_apply_unique_within_record_constraint().

        Args:
            record: Current partially-built record
            constraint_columns: List of columns in the constraint
            ignore_row_if: Ignore condition ('never', 'any_value_is_missing', 'all_values_are_missing')

        Returns:
            True if constraint should be applied, False otherwise

        """
        return self.constraint_handlers.should_apply_unique_within_record_constraint(
            record, constraint_columns, ignore_row_if
        )

    def _ensure_distinct_from_columns(
        self,
        value: Any,
        record: dict[str, Any],
        constraint_columns: list[str],
        current_col: str,
        enable_debug: bool,
    ) -> Any:
        """Ensure generated value differs from other columns in unique-within-record constraint.

        Delegates to constraint_handlers.ensure_distinct_from_columns().

        Args:
            value: Generated value to check/modify
            record: Current partially-built record
            constraint_columns: List of columns that must have distinct values
            current_col: Current column name
            enable_debug: Whether debug logging is enabled

        Returns:
            Modified value that is distinct from other columns in the group

        """
        return self.constraint_handlers.ensure_distinct_from_columns(
            value, record, constraint_columns, current_col, enable_debug
        )

    def _calculate_table_record_count(
        self, table_name: str, umf_data: dict[str, Any]
    ) -> int:
        """Calculate appropriate number of records based on relationship cardinality.

        Uses the relationship graph to identify base tables (no dependencies) and
        calculate record counts based on cardinality types.
        """
        # Check if table is in the graph
        if table_name not in self.graph.nodes:
            # Table not in graph (e.g., generated table) - use default sizing
            default_count = max(100, int(self.config.num_members * 0.1))
            self.logger.debug(
                f"Table {table_name} not in relationship graph, using default sizing: {default_count} records"
            )
            return default_count

        # Get table node from graph
        table_node = self.graph.nodes[table_name]

        # Identify base table(s) - tables with no dependencies
        if len(table_node.dependencies) == 0:
            self.logger.debug(
                f"Table {table_name} identified as base table (no dependencies), "
                + f"generating {self.config.num_members} records"
            )
            return self.config.num_members

        # Table has dependencies - calculate count based on relationship cardinality
        # Use UMF data to get cardinality information
        if "relationships" in umf_data and "incoming" in umf_data["relationships"]:
            for rel in umf_data["relationships"]["incoming"]:
                source_table = rel.get("source_table")
                if not source_table:
                    continue

                cardinality = rel.get("cardinality", {}).get("type", "one_to_many")

                if cardinality == "one_to_one":
                    record_count = self.config.num_members
                elif cardinality == "one_to_zero_or_one":
                    record_count = int(
                        self.config.num_members * self.config.relationship_density
                    )
                elif cardinality in ["one_to_many", "one_to_zero_or_many"]:
                    # Average 2-5 records per member
                    multiplier = random.uniform(2.0, 5.0)
                    record_count = int(
                        self.config.num_members
                        * multiplier
                        * self.config.relationship_density
                    )
                else:
                    # Unknown cardinality, use default
                    continue

                self.logger.debug(
                    f"Table {table_name} has {cardinality} relationship from {source_table}, "
                    + f"generating {record_count} records"
                )
                return record_count

        # Fallback: table has dependencies but no cardinality info in UMF
        default_count = max(100, int(self.config.num_members * 0.1))
        self.logger.debug(
            f"Table {table_name} has dependencies but no cardinality info, using default sizing: {default_count} records"
        )
        return default_count

    def _generate_filename_from_pattern(
        self, table_name: str, umf_data: dict[str, Any], records: list[dict]
    ) -> str:
        """Generate filename using pattern from UMF file_format.

        Delegates to filename_generator.generate_filename_from_pattern().

        Args:
            table_name: Name of the table
            umf_data: UMF specification
            records: Generated records (to extract filename column values)

        Returns:
            Generated filename with pattern or simple {table_name}.txt as fallback

        """
        return self.filename_generator.generate_filename_from_pattern(
            table_name, umf_data, records
        )

    def save_data(
        self, table_name: str, records: list[dict], umf_data: dict[str, Any]
    ) -> None:
        """Save generated data as pipe-delimited text files.

        Args:
            table_name: Name of the table
            records: Generated records
            umf_data: UMF specification containing column definitions

        """
        # Save directly to output directory, not in subdirectories
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not records:
            self.logger.warning(f"No records generated for {table_name}")
            return

        # Get column names from UMF, only including data columns
        # Filename-sourced and metadata columns will be added during Bronze.Raw ingestion
        umf_columns_data_unsorted = [
            col
            for col in umf_data.get("columns", [])
            if col.get("source", "data") in ["data"]
        ]

        # Sort columns by position to ensure correct output file column order
        # Position comes from explicit 'position' field or first Excel column alias (A-ZZ)
        # This is critical for provided tables where column order must match source file format
        # Create index map before sorting for stable fallback ordering
        original_indices = {
            id(col): idx for idx, col in enumerate(umf_columns_data_unsorted)
        }
        umf_columns_data = sorted(
            umf_columns_data_unsorted,
            key=lambda c: position_sort_key(
                _get_effective_position(c),
                original_indices[id(c)],  # Fallback to original order
            ),
        )
        umf_columns = [col["name"] for col in umf_columns_data]

        if not umf_columns:
            self.logger.error(f"No data columns defined in UMF for {table_name}")
            return

        # Validate first and last records to ensure consistent schema
        # (checking all records would be too expensive for large datasets)
        for idx in [0, len(records) - 1] if len(records) > 1 else [0]:
            record = records[idx]
            missing_cols = set(umf_columns) - set(record.keys())
            if missing_cols:
                self.logger.error(
                    f"Record {idx} for {table_name} missing columns: {sorted(missing_cols)}"
                )
                msg = (
                    f"Generated record missing required columns: {sorted(missing_cols)}"
                )
                raise ValueError(msg)

        # Check for extra columns (warning only, check first record)
        # Filename-sourced columns are expected in records but excluded from CSV output
        # Metadata columns (meta_*) are also expected in UMF but not generated
        filename_cols = {
            col["name"]
            for col in umf_data.get("columns", [])
            if col.get("source") == "filename"
        }
        extra_cols = (
            set(records[0].keys())
            - set(umf_columns)
            - filename_cols
            - set(PROVENANCE_COLUMNS.keys())
        )
        if extra_cols:
            self.logger.warning(
                f"{table_name} records have unexpected columns that will be ignored: {sorted(extra_cols)}"
            )

        # Generate filename from pattern if available
        filename = self._generate_filename_from_pattern(table_name, umf_data, records)

        # Detect filename collision: two tables with the same filename_pattern
        # (e.g., outreach_list and outreach_list_initial_mail both produce the same file).
        # Fall back to {table_name}.txt to avoid overwriting the first table's data.
        if filename in self._generated_filenames:
            prior_table = self._generated_filenames[filename]
            self.logger.warning(
                f"Filename collision: '{filename}' already written by '{prior_table}'. "
                f"Using '{table_name}.txt' for table '{table_name}' to avoid overwrite."
            )
            filename = f"{table_name}.txt"

        self._generated_filenames[filename] = table_name

        # Get delimiter from UMF file_format (default to pipe for backwards compatibility)
        file_format = umf_data.get("file_format", {})
        delimiter = file_format.get("delimiter", "|")

        # Save as delimited text file with UMF column order
        # CSV headers use canonical_name if available, otherwise use name
        csv_fieldnames = [
            col.get("canonical_name", col["name"]) for col in umf_columns_data
        ]

        txt_file = self.output_dir / filename
        with open(txt_file, "w", newline="", encoding="utf-8") as f:
            # Use snake_case names for field mapping (records use snake_case keys)
            writer = csv.DictWriter(
                f,
                fieldnames=umf_columns,  # Record field names (snake_case)
                delimiter=delimiter,
                extrasaction="ignore",  # Ignore extra columns not in fieldnames
            )
            # Write canonical names as headers instead of using writeheader()
            f.write(delimiter.join(csv_fieldnames) + "\n")
            writer.writerows(records)
        self.logger.debug(
            f"Saved delimited file: {txt_file} ({len(umf_columns)} columns)"
        )

        # Create symlink with simple table name for load-raw compatibility
        # load-raw expects files named {table}.txt, but we generate pattern-based names
        simple_filename = f"{table_name}.txt"
        if filename != simple_filename:
            simple_symlink = self.output_dir / simple_filename
            # Remove existing symlink if it exists
            if simple_symlink.is_symlink() or simple_symlink.exists():
                simple_symlink.unlink()
            simple_symlink.symlink_to(filename)
            self.logger.debug(f"Created symlink: {simple_filename} -> {filename}")

    def generate_summary_report(self) -> None:
        """Generate summary report of data generation."""
        report: GenerationReport = {
            "generation_timestamp": self.config.get_reference_date().isoformat(),
            "configuration": {
                "num_members": self.config.num_members,
                "relationship_density": self.config.relationship_density,
                "temporal_range_days": self.config.temporal_range_days,
            },
            "tables_generated": {},
            "key_statistics": {
                "total_tables": len(self.generated_data),
                "total_records": sum(
                    len(records) for records in self.generated_data.values()
                ),
                "unique_member_ids": len(self.generators.member_ids),
            },
        }

        for table_name, records in self.generated_data.items():
            table_info: TableGenerationInfo = {
                "record_count": len(records),
                "columns": list(records[0].keys()) if records else [],
                "column_count": len(records[0].keys()) if records else 0,
            }
            report["tables_generated"][table_name] = table_info

        # Save summary report
        summary_file = self.output_dir / "GENERATION_SUMMARY.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)

        self.logger.info(
            f"Generated {report['key_statistics']['total_records']} records across {report['key_statistics']['total_tables']} tables"
        )
        self.logger.info(f"Summary saved to: {summary_file}")

    def run_generation(self) -> bool:
        """Execute the complete sample data generation process."""
        try:
            self.logger.info("Starting sample data generation")

            # Initialize random seed for reproducibility
            if self.config.random_seed is not None:
                random.seed(self.config.random_seed)
                self.logger.debug(f"Random seed set to {self.config.random_seed}")
            else:
                self.logger.debug("Using random seed (non-deterministic)")

            # Load UMF specifications
            umf_files = self.load_umf_files()

            # Build relationship dependencies
            self.build_relationship_graph(umf_files)

            # Get generation order
            generation_order = self.graph.get_generation_order()

            # Pre-calculate row counts for all tables (needed for pool sizing)
            table_row_counts = {}
            for table_name in generation_order:
                umf_data = umf_files[table_name]
                num_records = self._calculate_table_record_count(table_name, umf_data)
                table_row_counts[table_name] = num_records

            self.logger.info(
                f"Calculated row counts for {len(table_row_counts)} tables: "
                + f"{dict(list(table_row_counts.items())[:3])}{'...' if len(table_row_counts) > 3 else ''}"
            )

            # Discover cross-pipeline foreign keys and load seeds from UC
            cross_pipeline_fks = self._discover_cross_pipeline_fks(umf_files)
            cross_pipeline_seeds = self._load_cross_pipeline_seeds(cross_pipeline_fks)

            # Pre-generate key pools for joinable foreign keys with row count info
            self.key_registry.pre_generate_key_pools(
                self.generators, umf_files, table_row_counts, cross_pipeline_seeds
            )

            # Log foreign key pool statistics
            fk_manager = self.key_registry.foreign_key_manager
            self.logger.info(
                f"Foreign key pools ready: {len(fk_manager.pools)} equivalence groups"
            )
            for group_id, pool in fk_manager.pools.items():
                # Find all columns in this group
                columns = fk_manager.get_columns_for_group(group_id)
                self.logger.debug(
                    f"  Pool '{group_id}': {len(pool)} values for {len(columns)} columns: {columns[:5]}{'...' if len(columns) > 5 else ''}"
                )

            # Generate data for each table in dependency order
            for table_name in generation_order:
                umf_data = umf_files[table_name]
                num_records = table_row_counts[table_name]

                # Generate the data
                records = self.generate_table_data(table_name, umf_data, num_records)
                self.generated_data[table_name] = records

                # Save immediately with UMF schema for validation
                self.save_data(table_name, records, umf_data)

            # Generate summary report
            self.generate_summary_report()

            self.logger.info("Sample data generation completed successfully")
            return True

        except Exception as e:
            self.logger.exception(f"Sample data generation failed: {e}")
            raise


__all__ = ["SampleDataGenerator"]
