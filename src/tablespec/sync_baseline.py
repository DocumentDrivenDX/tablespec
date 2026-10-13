"""Sync metadata columns and programmatic baseline validations.

This module provides functionality to keep metadata columns and baseline validations
synchronized across table definitions. It ensures that:

1. All tables have the required metadata columns (meta_source_name, meta_load_dt, etc.)
2. Baseline validations stay up-to-date with changes to the baseline generator
3. Domain type validations are synced based on column domain_type
4. User customizations (severity changes) are preserved
5. Conflicts (modified rule content) are detected and reported

The sync operation is idempotent and safe to run multiple times.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, TypedDict

try:
    from ruamel.yaml import YAML

    _ruamel_available = True
except ImportError:
    _ruamel_available = False

from tablespec.gx_baseline import BaselineExpectationGenerator

try:
    from tablespec.ingestion.constants import PROVENANCE_COLUMNS

    _provenance_columns_available = True
except ImportError:
    _provenance_columns_available = False

try:
    from tablespec.umf_loader import UMFLoader

    _umf_loader_available = True
except ImportError:
    _umf_loader_available = False

logger = logging.getLogger(__name__)


if _provenance_columns_available:
    _provenance_column_source: dict[str, dict[str, Any]] = PROVENANCE_COLUMNS
else:
    # Fallback for environments that do not import the ingestion constants.
    _provenance_column_source = {
        "meta_source_name": {
            "name": "meta_source_name",
            "data_type": "VARCHAR",
            "source": "metadata",
            "description": "Source name (e.g. filename or source table) recorded at ingest",
        },
        "meta_source_checksum": {
            "name": "meta_source_checksum",
            "data_type": "VARCHAR",
            "source": "metadata",
            "description": "Checksum of the source artifact (ingest-computed)",
        },
        "meta_load_dt": {
            "name": "meta_load_dt",
            "data_type": "DATETIME",
            "source": "metadata",
            "description": "Timestamp when ingestion ran",
        },
        "meta_snapshot_dt": {
            "name": "meta_snapshot_dt",
            "data_type": "DATETIME",
            "source": "metadata",
            "description": "Snapshot timestamp of the source data",
        },
        "meta_source_offset": {
            "name": "meta_source_offset",
            "data_type": "INTEGER",
            "source": "metadata",
            "description": "Row offset within the source (ingest-assigned)",
        },
        "meta_checksum": {
            "name": "meta_checksum",
            "data_type": "VARCHAR",
            "source": "metadata",
            "description": "Row content checksum for change detection",
        },
        "meta_pipeline_version": {
            "name": "meta_pipeline_version",
            "data_type": "VARCHAR",
            "source": "metadata",
            "description": "Pipeline version that produced the row",
        },
        "meta_component": {
            "name": "meta_component",
            "data_type": "VARCHAR",
            "source": "metadata",
            "description": "Pipeline component that produced the row",
        },
    }

# Metadata column canonical definitions
METADATA_COLUMN_DEFINITIONS = {
    name: {
        **definition,
        "nullable": {"MD": False, "ME": False, "MP": False},
    }
    for name, definition in _provenance_column_source.items()
}


def get_metadata_column_definitions(
    columns: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return metadata column definitions with nullable shape matching the table context."""
    context_keys: list[str] = []
    for column in columns or []:
        nullable = column.get("nullable")
        if isinstance(nullable, dict):
            context_keys = list(nullable.keys())
            break

    definitions = {
        name: {
            **definition,
            "nullable": (
                {context: False for context in context_keys} if context_keys else False
            ),
        }
        for name, definition in METADATA_COLUMN_DEFINITIONS.items()
    }
    return definitions


@dataclass
class ConflictDetail:
    """Details about a validation rule conflict."""

    column_name: str
    rule_type: str
    canonical_kwargs: dict[str, Any]
    existing_kwargs: dict[str, Any]
    difference: str


@dataclass
class ValidationSyncChange:
    """Base class for validation rule sync changes."""

    column_name: str
    rule_type: str
    kwargs: dict[str, Any]
    generated_from: str  # 'baseline' or 'domain_type'


@dataclass
class ValidationAdded(ValidationSyncChange):
    """A new validation rule was added."""


@dataclass
class ValidationRemoved(ValidationSyncChange):
    """A validation rule was removed (outdated)."""


@dataclass
class ValidationUpgraded(ValidationSyncChange):
    """An unmarked validation was upgraded to programmatic."""


@dataclass
class ValidationSeverityPreserved(ValidationSyncChange):
    """A validation matched but user's custom severity was preserved."""

    user_severity: str
    canonical_severity: str


class SyncStats(TypedDict):
    """Statistics from sync operation."""

    added: int
    upgraded: int
    conflicts: int
    severity_preserved: int
    removed: int
    conflict_details: list[ConflictDetail]
    added_details: list[ValidationAdded]
    removed_details: list[ValidationRemoved]
    upgraded_details: list[ValidationUpgraded]
    severity_preserved_details: list[ValidationSeverityPreserved]


@dataclass
class SyncResult:
    """Results from syncing a single table."""

    table_name: str
    columns_added: int = 0
    columns_updated: int = 0
    columns_skipped: int = 0  # User-modified columns
    validations_added: int = 0
    validations_upgraded: int = 0  # Unmarked validations upgraded to programmatic
    validations_conflicts: int = 0
    validations_severity_preserved: int = 0
    conflicts: list[ConflictDetail] = field(default_factory=list)

    # Detailed tracking of validation changes
    validations_added_details: list[ValidationAdded] = field(default_factory=list)
    validations_removed_details: list[ValidationRemoved] = field(default_factory=list)
    validations_upgraded_details: list[ValidationUpgraded] = field(default_factory=list)
    validations_severity_preserved_details: list[ValidationSeverityPreserved] = field(
        default_factory=list
    )

    @property
    def has_conflicts(self) -> bool:
        """Check if any conflicts were detected."""
        return len(self.conflicts) > 0

    def summary_lines(self) -> list[str]:
        """Generate human-readable summary lines."""
        lines = [f"{self.table_name}:"]
        if self.columns_added > 0:
            lines.append(f"  Columns: {self.columns_added} added")
        if self.columns_updated > 0:
            lines.append(f"  Columns: {self.columns_updated} updated")
        if self.columns_skipped > 0:
            lines.append(f"  Columns: {self.columns_skipped} skipped (user-modified)")

        validation_parts = []
        if self.validations_added > 0:
            validation_parts.append(f"{self.validations_added} added")
        if self.validations_upgraded > 0:
            validation_parts.append(f"{self.validations_upgraded} upgraded")
        if self.validations_conflicts > 0:
            validation_parts.append(f"{self.validations_conflicts} conflicts")
        if self.validations_severity_preserved > 0:
            validation_parts.append(
                f"{self.validations_severity_preserved} custom severities preserved"
            )

        if validation_parts:
            lines.append(f"  Validations: {', '.join(validation_parts)}")

        return lines

    @staticmethod
    def format_validation_rule(rule_type: str, kwargs: dict[str, Any]) -> str:
        """Format validation rule concisely for display.

        Shows rule type and key parameters (excluding column name for brevity).

        Args:
            rule_type: The expectation type (e.g., expect_column_values_to_match_regex)
            kwargs: The kwargs dict from the validation rule

        Returns:
            Formatted string like: expect_column_values_to_match_regex (regex=^[A-Z]{2}$)

        """
        # Remove column from kwargs since it's contextual (shown separately)
        relevant_kwargs = {k: v for k, v in kwargs.items() if k != "column"}

        # Format key-value pairs concisely
        if relevant_kwargs:
            # Truncate long values for readability
            def truncate_value(v: Any) -> str:
                s = str(v)
                return s if len(s) <= 50 else f"{s[:47]}..."

            params = ", ".join(
                f"{k}={truncate_value(v)}" for k, v in relevant_kwargs.items()
            )
            return f"{rule_type} ({params})"

        return rule_type


class BaselineSyncer:
    """Sync metadata columns and baseline validations across tables.

    This class provides idempotent sync operations that:
    - Add missing metadata columns
    - Update metadata columns to canonical definitions
    - Sync programmatic baseline and domain type validations
    - Preserve user customizations (severity changes)
    - Detect and report conflicts (modified rule content)

    Requires ruamel.yaml and UMFLoader to be available.
    """

    def __init__(self) -> None:
        """Initialize the baseline syncer."""
        if not _ruamel_available:
            msg = "ruamel.yaml is required for BaselineSyncer"
            raise ImportError(msg)
        if not _umf_loader_available:
            msg = "UMFLoader is required for BaselineSyncer"
            raise ImportError(msg)

        self.logger = logging.getLogger(self.__class__.__name__)
        self.baseline_generator = BaselineExpectationGenerator()
        self.umf_loader = UMFLoader()

        # Configure YAML handler for deterministic output
        self.yaml = YAML()
        self.yaml.default_flow_style = False
        self.yaml.preserve_quotes = True
        self.yaml.width = 100

    def sync_table(
        self,
        table_path: Path,
        dry_run: bool = False,
        aggressive: bool = False,
        clean_outdated: bool = False,
    ) -> SyncResult:
        """Sync metadata columns and validations for a single table.

        Args:
            table_path: Path to table directory (contains columns/ subdirectory)
            dry_run: If True, report what would be done without making changes
            aggressive: If True, match validations without generated_from by structure
            clean_outdated: If True, remove outdated baseline/domain_type validations

        Returns:
            SyncResult with statistics and conflicts

        """
        table_name = table_path.name
        self.logger.info(f"Syncing table: {table_name}")

        result = SyncResult(table_name=table_name)

        # Ensure columns directory exists
        columns_dir = table_path / "columns"
        if not columns_dir.exists():
            if not dry_run:
                columns_dir.mkdir(parents=True)
            self.logger.info(f"Created columns directory: {columns_dir}")

        # Sync metadata columns
        self._sync_metadata_columns(table_path, result, dry_run)

        # Sync validations for all columns
        self._sync_validations(table_path, result, dry_run, aggressive, clean_outdated)

        return result

    def sync_pipeline(
        self,
        pipeline_path: Path,
        dry_run: bool = False,
        aggressive: bool = False,
        clean_outdated: bool = False,
    ) -> dict[str, SyncResult]:
        """Sync all tables in a pipeline.

        Args:
            pipeline_path: Path to pipeline directory
            dry_run: If True, report what would be done without making changes
            aggressive: If True, match validations without generated_from by structure
            clean_outdated: If True, remove outdated baseline/domain_type validations

        Returns:
            Dictionary mapping table names to SyncResults

        """
        self.logger.info(f"Syncing pipeline: {pipeline_path.name}")

        results = {}
        for table_path in sorted(pipeline_path.iterdir()):
            if table_path.is_dir() and not table_path.name.startswith("."):
                # Check if it's a table directory (has table.yaml or columns/)
                if (table_path / "table.yaml").exists() or (
                    table_path / "columns"
                ).exists():
                    result = self.sync_table(
                        table_path, dry_run, aggressive, clean_outdated
                    )
                    results[table_path.name] = result

        return results

    def _sync_metadata_columns(
        self, table_path: Path, result: SyncResult, dry_run: bool
    ) -> None:
        """Sync metadata columns for a table."""
        columns_dir = table_path / "columns"

        for meta_col_name, canonical_def in METADATA_COLUMN_DEFINITIONS.items():
            column_file = columns_dir / f"{meta_col_name}.yaml"

            if not column_file.exists():
                # Add new metadata column
                self._create_metadata_column_file(column_file, canonical_def, dry_run)
                if not dry_run:
                    self._validate_written_table(table_path)
                result.columns_added += 1
            else:
                # Check if existing column matches canonical
                existing = self._load_column_file(column_file)
                if self._columns_match(canonical_def, existing.get("column", {})):
                    result.columns_skipped += 1
                else:
                    # Update to canonical definition
                    if not dry_run:
                        self._update_metadata_column_file(
                            column_file, canonical_def, existing
                        )
                        self._validate_written_table(table_path)
                    result.columns_updated += 1
                    self.logger.info(f"Updated metadata column: {meta_col_name}")

    def _sync_validations(
        self,
        table_path: Path,
        result: SyncResult,
        dry_run: bool,
        aggressive: bool,
        clean_outdated: bool,
    ) -> None:
        """Sync baseline and domain type validations for all columns in a table."""
        columns_dir = table_path / "columns"

        if not columns_dir.exists():
            return

        # Load full UMF to generate baseline expectations
        try:
            umf = self.umf_loader.load(table_path)
        except Exception as e:
            self.logger.exception(f"Failed to load UMF for {table_path.name}: {e}")
            return

        # Convert UMF to dict for baseline generator
        umf_dict = umf.model_dump(mode="python", exclude_none=True)

        # Generate canonical baseline + domain type validations
        canonical_expectations = self.baseline_generator.generate_baseline_expectations(
            umf_dict, include_structural=False
        )

        # Group by column
        canonical_by_column: dict[str, list[dict]] = {}
        for exp in canonical_expectations:
            col_name = exp.get("kwargs", {}).get("column")
            if col_name:
                if col_name not in canonical_by_column:
                    canonical_by_column[col_name] = []
                canonical_by_column[col_name].append(exp)

        # Sync validations for each column
        for column_file in sorted(columns_dir.glob("*.yaml")):
            col_name = column_file.stem
            canonical_exps = canonical_by_column.get(col_name, [])

            if not canonical_exps:
                continue

            existing_data = self._load_column_file(column_file)
            existing_validations = existing_data.get("validations", [])

            # Sync validations
            updated_validations, col_result = self._sync_column_validations(
                col_name,
                canonical_exps,
                existing_validations,
                aggressive,
                clean_outdated,
            )

            # Update result statistics
            result.validations_added += col_result["added"]
            result.validations_upgraded += col_result["upgraded"]
            result.validations_conflicts += col_result["conflicts"]
            result.validations_severity_preserved += col_result["severity_preserved"]
            result.conflicts.extend(col_result["conflict_details"])

            # Accumulate detailed change tracking
            result.validations_added_details.extend(col_result["added_details"])
            result.validations_removed_details.extend(col_result["removed_details"])
            result.validations_upgraded_details.extend(col_result["upgraded_details"])
            result.validations_severity_preserved_details.extend(
                col_result["severity_preserved_details"]
            )

            # Write updated validations
            if not dry_run and (
                col_result["added"] > 0
                or col_result["upgraded"] > 0
                or col_result.get("removed", 0) > 0
            ):
                existing_data["validations"] = updated_validations
                self._save_column_file(column_file, existing_data)
                self._validate_written_table(table_path)

    def _sync_column_validations(
        self,
        col_name: str,
        canonical: list[dict],
        existing: list[dict],
        aggressive: bool = False,
        clean_outdated: bool = False,
    ) -> tuple[list[dict], SyncStats]:
        """Sync validations for a single column.

        Args:
            col_name: Column name
            canonical: Canonical validations from baseline generator
            existing: Existing validations from column YAML
            aggressive: If True, match unmarked validations by structure
            clean_outdated: If True, remove outdated baseline/domain_type validations

        Returns:
            Tuple of (updated_validations, stats_dict)

        """
        stats: SyncStats = {
            "added": 0,
            "upgraded": 0,
            "conflicts": 0,
            "severity_preserved": 0,
            "removed": 0,
            "conflict_details": [],
            "added_details": [],
            "removed_details": [],
            "upgraded_details": [],
            "severity_preserved_details": [],
        }

        # Build index of existing validations by type
        existing_programmatic = {}
        existing_unmarked = []
        existing_user = []

        for exp in existing:
            generated_from = exp.get("meta", {}).get("generated_from")
            if generated_from in ("baseline", "domain_type"):
                # Tier 1: Programmatic with marker
                key = self._normalize_expectation(exp)
                existing_programmatic[key] = exp
            elif generated_from in (None, "", "user_input") and aggressive:
                # Tier 2: Unmarked validation in aggressive mode
                existing_unmarked.append(exp)
            else:
                # User validation or non-aggressive mode
                existing_user.append(exp)

        # Process canonical expectations
        updated_validations = []

        for canonical_exp in canonical:
            canonical_key = self._normalize_expectation(canonical_exp)

            if canonical_key in existing_programmatic:
                # Tier 1: Standard match with marked validation
                existing_exp = existing_programmatic[canonical_key]
                comparison = self._compare_expectations(canonical_exp, existing_exp)

                if comparison == "match":
                    # Exact match, keep existing
                    updated_validations.append(existing_exp)
                elif comparison == "severity_only":
                    # Only severity differs, preserve user customization
                    updated_validations.append(existing_exp)
                    stats["severity_preserved"] += 1
                    stats["severity_preserved_details"].append(
                        ValidationSeverityPreserved(
                            column_name=col_name,
                            rule_type=canonical_exp["type"],
                            kwargs=canonical_exp.get("kwargs", {}),
                            generated_from=canonical_exp.get("meta", {}).get(
                                "generated_from", ""
                            ),
                            user_severity=existing_exp.get("meta", {}).get(
                                "severity", ""
                            ),
                            canonical_severity=canonical_exp.get("meta", {}).get(
                                "severity", ""
                            ),
                        )
                    )
                else:
                    # Conflict: rule content differs
                    updated_validations.append(existing_exp)  # Keep existing
                    stats["conflicts"] += 1
                    stats["conflict_details"].append(
                        ConflictDetail(
                            column_name=col_name,
                            rule_type=canonical_exp["type"],
                            canonical_kwargs=canonical_exp.get("kwargs", {}),
                            existing_kwargs=existing_exp.get("kwargs", {}),
                            difference=comparison,
                        )
                    )
                    self.logger.warning(
                        f"Conflict in {col_name}.{canonical_exp['type']}: {comparison}"
                    )

                # Remove from index to track what we've processed
                del existing_programmatic[canonical_key]
            elif aggressive:
                # Tier 2: Check unmarked validations for structural match
                matched = self._find_structural_match(canonical_exp, existing_unmarked)
                if matched:
                    # Upgrade: replace with canonical (adds generated_from marker)
                    updated_validations.append(canonical_exp)
                    existing_unmarked.remove(matched)
                    stats["upgraded"] += 1
                    stats["upgraded_details"].append(
                        ValidationUpgraded(
                            column_name=col_name,
                            rule_type=canonical_exp["type"],
                            kwargs=canonical_exp.get("kwargs", {}),
                            generated_from=canonical_exp.get("meta", {}).get(
                                "generated_from", ""
                            ),
                        )
                    )
                    self.logger.info(
                        f"Upgraded unmarked validation in {col_name}: {canonical_exp['type']}"
                    )
                else:
                    # New canonical validation
                    updated_validations.append(canonical_exp)
                    stats["added"] += 1
                    stats["added_details"].append(
                        ValidationAdded(
                            column_name=col_name,
                            rule_type=canonical_exp["type"],
                            kwargs=canonical_exp.get("kwargs", {}),
                            generated_from=canonical_exp.get("meta", {}).get(
                                "generated_from", ""
                            ),
                        )
                    )
            else:
                # Non-aggressive mode: add as new
                updated_validations.append(canonical_exp)
                stats["added"] += 1
                stats["added_details"].append(
                    ValidationAdded(
                        column_name=col_name,
                        rule_type=canonical_exp["type"],
                        kwargs=canonical_exp.get("kwargs", {}),
                        generated_from=canonical_exp.get("meta", {}).get(
                            "generated_from", ""
                        ),
                    )
                )

        # Handle remaining programmatic validations that weren't matched
        if clean_outdated:
            # Clean mode: remove outdated programmatic validations
            stats["removed"] = len(existing_programmatic)
            if stats["removed"] > 0:
                # Track details of removed validations
                for exp in existing_programmatic.values():
                    stats["removed_details"].append(
                        ValidationRemoved(
                            column_name=col_name,
                            rule_type=exp["type"],
                            kwargs=exp.get("kwargs", {}),
                            generated_from=exp.get("meta", {}).get(
                                "generated_from", ""
                            ),
                        )
                    )
                self.logger.info(
                    f"Removed {stats['removed']} outdated baseline/domain validation(s) from {col_name}"
                )
        else:
            # Safe mode: keep any remaining programmatic validations
            # (These might be from an older baseline version)
            updated_validations.extend(existing_programmatic.values())

        # Add back all remaining unmarked and user validations
        updated_validations.extend(existing_unmarked)
        updated_validations.extend(existing_user)

        return updated_validations, stats

    def _normalize_expectation(self, exp: dict) -> tuple:
        """Normalize expectation for comparison (ignore severity and metadata).

        Returns:
            Tuple of (type, sorted_kwargs_items) for comparison

        """
        exp_type = exp.get("type")
        kwargs = exp.get("kwargs", {})

        # Convert kwargs values to hashable types (lists -> tuples, dicts -> sorted tuples)
        def make_hashable(value):
            if isinstance(value, list):
                return tuple(make_hashable(item) for item in value)
            if isinstance(value, dict):
                return tuple(sorted((k, make_hashable(v)) for k, v in value.items()))
            return value

        hashable_kwargs = {k: make_hashable(v) for k, v in kwargs.items()}

        # Sort kwargs for consistent comparison
        sorted_kwargs = tuple(sorted(hashable_kwargs.items()))

        return (exp_type, sorted_kwargs)

    def _compare_expectations(self, canonical: dict, existing: dict) -> str:
        """Compare canonical and existing expectations.

        Returns:
            "match" - Exact match (including severity)
            "severity_only" - Only severity differs
            str - Description of conflict if rule content differs

        """
        canonical_norm = self._normalize_expectation(canonical)
        existing_norm = self._normalize_expectation(existing)

        if canonical_norm != existing_norm:
            # Rule content differs (type or kwargs)
            canonical_kwargs = canonical.get("kwargs", {})
            existing_kwargs = existing.get("kwargs", {})

            diff_keys = set(canonical_kwargs.keys()) ^ set(existing_kwargs.keys())
            if diff_keys:
                return f"Different kwargs keys: {diff_keys}"

            # Find which values differ
            for key in canonical_kwargs:
                if canonical_kwargs[key] != existing_kwargs.get(key):
                    return (
                        f"{key}: {canonical_kwargs[key]} != {existing_kwargs.get(key)}"
                    )

            return "Unknown difference in rule structure"

        # Same rule, check severity
        canonical_severity = canonical.get("meta", {}).get("severity")
        existing_severity = existing.get("meta", {}).get("severity")

        if canonical_severity == existing_severity:
            return "match"
        return "severity_only"

    def _find_structural_match(
        self, canonical: dict, unmarked_list: list[dict]
    ) -> dict | None:
        """Find an unmarked validation that structurally matches canonical.

        Args:
            canonical: Canonical validation from baseline generator
            unmarked_list: List of validations without generated_from marker

        Returns:
            The matched validation or None if no match found

        """
        canonical_norm = self._normalize_expectation(canonical)

        for exp in unmarked_list:
            exp_norm = self._normalize_expectation(exp)
            if canonical_norm == exp_norm:
                return exp

        return None

    def _columns_match(self, canonical: dict, existing: dict) -> bool:
        """Check if column definitions match (ignoring user notes)."""
        # Compare key fields only
        key_fields = ["name", "data_type", "source", "description", "nullable"]

        return all(canonical.get(field) == existing.get(field) for field in key_fields)

    def _create_metadata_column_file(
        self, column_file: Path, canonical_def: dict, dry_run: bool
    ) -> None:
        """Create a new metadata column YAML file with baseline validations."""
        # Generate baseline validations for this column
        validations = self.baseline_generator.generate_baseline_column_expectations(
            canonical_def
        )

        column_data = {"column": canonical_def, "validations": validations}

        if not dry_run:
            self._save_column_file(column_file, column_data)

        self.logger.info(f"Added metadata column: {canonical_def['name']}")

    def _update_metadata_column_file(
        self, column_file: Path, canonical_def: dict, existing_data: dict
    ) -> None:
        """Update existing metadata column to canonical definition."""
        # Preserve validations and any user notes
        existing_data["column"] = canonical_def
        self._save_column_file(column_file, existing_data)

    def _validate_written_table(self, table_path: Path) -> None:
        """Reload a table after a write and fail closed if it no longer loads."""
        try:
            self.umf_loader.load(table_path)
        except Exception as e:
            msg = f"Validation failed after writing {table_path}: {e}"
            self.logger.error(msg)
            raise ValueError(msg) from e

    def _sort_recursive(self, obj: Any) -> Any:
        """Sort object recursively for deterministic YAML output.

        IMPORTANT: Never sorts lists - order matters for columns and validations!
        Only sorts dictionary keys for deterministic output.

        Args:
            obj: Object to sort

        Returns:
            Sorted dict keys (recursively) but preserved list order

        """
        if isinstance(obj, dict):
            # Filter out None values, sort keys
            filtered = {k: v for k, v in obj.items() if v is not None}
            return {
                k: self._sort_recursive(filtered[k]) for k in sorted(filtered.keys())
            }

        if isinstance(obj, list):
            # NEVER sort lists - order matters!
            # Columns and validations must stay in original order for in-place edits
            # to produce minimal diffs without spurious reordering
            return [self._sort_recursive(item) for item in obj]

        return obj

    def _strip_trailing_whitespace(self, obj: Any) -> Any:
        """Recursively strip trailing whitespace from all string values.

        Args:
            obj: Object to clean

        Returns:
            Object with trailing whitespace removed from all strings

        """
        if isinstance(obj, str):
            return obj.rstrip()

        if isinstance(obj, dict):
            return {k: self._strip_trailing_whitespace(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self._strip_trailing_whitespace(item) for item in obj]

        return obj

    def _load_column_file(self, column_file: Path) -> dict:
        """Load column YAML file."""
        # Use self.yaml for consistent loading
        with column_file.open("r", encoding="utf-8") as f:
            return self.yaml.load(f) or {}

    def _save_column_file(self, column_file: Path, data: dict) -> None:
        """Save column YAML file with proper formatting.

        Uses deterministic YAML output with:
        - Recursive key sorting for deterministic output
        - Preserved list order (critical for validations)
        - Trailing whitespace removal

        """
        from io import StringIO

        # Sort dictionary keys recursively for deterministic output
        sorted_data = self._sort_recursive(data)

        # Strip trailing whitespace from all strings
        cleaned_data = self._strip_trailing_whitespace(sorted_data)

        # Try to use formatting module if available, otherwise fallback
        try:
            from tablespec.formatting import format_yaml_dict

            formatted_yaml = format_yaml_dict(cleaned_data)
        except ImportError:
            # Fallback to unformatted YAML if formatting module not available
            output = StringIO()
            self.yaml.dump(cleaned_data, output)
            formatted_yaml = output.getvalue()

        # Write once to disk
        column_file.parent.mkdir(parents=True, exist_ok=True)
        column_file.write_text(formatted_yaml, encoding="utf-8")
