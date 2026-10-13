"""Display and validate survivorship rules for generated tables.

Provides utilities for viewing survivorship mappings in human-readable format
and validating that all survivorship references are valid.
"""

import json
from pathlib import Path
from typing import Any


def load_survivorship(table_path: Path) -> dict[str, Any] | None:
    """Load survivorship rules from a table.

    Supports both:
    - Split format: Table directory loaded via UMFLoader (derivations in column files)
    - Compiled format: Single JSON tablespec file with derivations field

    Args:
        table_path: Path to table directory (split) or JSON file (compiled)

    Returns:
        Survivorship data dict, or None if not found

    """
    # If it's a file, assume it's compiled JSON tablespec
    if table_path.is_file():
        if table_path.suffix == ".json":
            with open(table_path) as f:
                umf_data = json.load(f)
            # Return derivations if present
            if "derivations" in umf_data:
                return umf_data["derivations"]
        return None

    # Otherwise it's a directory (split format)
    if not table_path.is_dir():
        return None

    # Use UMF loader to properly consolidate column-level derivations
    try:
        from tablespec.umf_loader import UMFLoader

        loader = UMFLoader()
        umf = loader.load(table_path)
        return umf.derivations
    except ImportError:
        # UMFLoader not available yet
        return None
    except Exception:
        # If loading fails, return None
        return None


class SurvivorshipValidator:
    """Validate survivorship rules for correctness and consistency."""

    @staticmethod
    def validate(
        surv_data: dict[str, Any],
        all_tables: dict[str, list[str]] | None = None,
    ) -> tuple[bool, list[str]]:
        """Validate survivorship rules.

        Checks that:
        1. All required sections are present and properly structured
        2. All referenced tables and columns exist (if all_tables provided)
        3. All strategies referenced are defined

        Args:
            surv_data: Survivorship data dictionary
            all_tables: Optional dict mapping table names to list of column names

        Returns:
            (is_valid, list of error messages)

        """
        errors = []

        if not isinstance(surv_data, dict):
            return False, ["Root object is not a dict"]

        # Check for required sections
        if "mappings" not in surv_data:
            errors.append("Missing 'mappings' section")
            return False, errors

        mappings = surv_data["mappings"]
        if not isinstance(mappings, dict):
            errors.append("mappings must be a dict")
            return False, errors

        # Get defined strategies
        defined_strategies = set(surv_data.get("survivorship_strategies", {}).keys())

        # Validate each mapping
        for col_name, mapping in mappings.items():
            SurvivorshipValidator._validate_mapping(
                col_name, mapping, defined_strategies, all_tables, errors
            )

        return len(errors) == 0, errors

    @staticmethod
    def _validate_mapping(
        col_name: str,
        mapping: Any,
        defined_strategies: set[str],
        all_tables: dict[str, list[str]] | None,
        errors: list[str],
    ) -> None:
        """Validate a single column mapping."""
        if not isinstance(mapping, dict):
            errors.append(f"Column '{col_name}': mapping is not a dict")
            return

        # Check survivorship
        survivorship = mapping.get("survivorship")
        if not survivorship:
            errors.append(f"Column '{col_name}': missing 'survivorship' key")
            return

        if not isinstance(survivorship, dict):
            errors.append(f"Column '{col_name}': survivorship is not a dict")
            return

        # Validate strategy
        strategy = survivorship.get("strategy")
        if not strategy:
            errors.append(f"Column '{col_name}': survivorship missing 'strategy'")
        elif defined_strategies and strategy not in defined_strategies:
            errors.append(
                f"Column '{col_name}': strategy '{strategy}' not defined in survivorship_strategies"
            )

        # Check for explanation field (canonical documentation field)
        if "explanation" not in survivorship:
            errors.append(f"Column '{col_name}': survivorship missing 'explanation'")

        # Validate candidates
        SurvivorshipValidator._validate_candidates(
            col_name, mapping, all_tables, errors
        )

    @staticmethod
    def _validate_candidates(
        col_name: str,
        mapping: dict[str, Any],
        all_tables: dict[str, list[str]] | None,
        errors: list[str],
    ) -> None:
        """Validate candidates list for a mapping."""
        candidates = mapping.get("candidates", [])
        if not isinstance(candidates, list):
            errors.append(f"Column '{col_name}': candidates must be a list")
            return

        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                errors.append(f"Column '{col_name}', candidate {i}: not a dict")
                continue

            # Use Pydantic model for validation if available
            try:
                from tablespec.models.umf import DerivationCandidate

                try:
                    validated_candidate = DerivationCandidate(**candidate)
                except Exception as e:
                    errors.append(f"Column '{col_name}', candidate {i}: {e!s}")
                    continue
            except ImportError:
                # DerivationCandidate not available, do basic validation
                validated_candidate = None
                if "table" not in candidate:
                    errors.append(
                        f"Column '{col_name}', candidate {i}: missing 'table' field"
                    )
                    continue

            # Validate table and column if all_tables provided
            if all_tables:
                if validated_candidate is not None:
                    table = validated_candidate.table
                    column = validated_candidate.column
                else:
                    table = candidate.get("table", "")
                    column = candidate.get("column")

                if table not in all_tables:
                    errors.append(
                        f"Column '{col_name}', candidate {i}: referenced table '{table}' does not exist"
                    )
                elif column and column not in all_tables[table]:
                    # Only validate column existence if column is specified (not just expression)
                    errors.append(
                        f"Column '{col_name}', candidate {i}: column '{column}' not found in table '{table}'"
                    )


def format_survivorship(surv_data: dict[str, Any], verbose: bool = False) -> str:
    """Format survivorship data for display.

    Args:
        surv_data: Survivorship data dictionary
        verbose: If True, show all details; otherwise show summary

    Returns:
        Formatted string for display

    """
    lines = []

    # Metadata
    metadata = surv_data.get("metadata", {})
    if metadata:
        lines.append("Metadata")
        lines.append(f"  Table: {metadata.get('table_name', 'N/A')}")
        lines.append(f"  Description: {metadata.get('description', 'N/A')}")
        lines.append("")

    # Survivorship strategies
    strategies = surv_data.get("survivorship_strategies", {})
    if strategies and verbose:
        lines.append("Survivorship Strategies")
        for strategy_name, strategy_spec in strategies.items():
            lines.append(f"  - {strategy_name}")
            description = strategy_spec.get("description", "")
            if description:
                lines.append(f"    {description}")
        lines.append("")

    # Column mappings
    mappings = surv_data.get("mappings", {})
    if mappings:
        lines.append("Column Survivorship Mappings")
        lines.append("")

        for col_name in sorted(mappings.keys()):
            mapping = mappings[col_name]
            survivorship = mapping.get("survivorship", {})
            strategy = survivorship.get("strategy", "N/A")
            description = survivorship.get("description", "N/A")
            candidates = mapping.get("candidates", [])

            lines.append(f"  {col_name}")
            lines.append(f"    Strategy: {strategy}")
            lines.append(f"    Description: {description}")

            if candidates:
                lines.append(f"    Sources ({len(candidates)}):")
                for candidate in sorted(
                    candidates, key=lambda c: c.get("priority", 999)
                ):
                    priority = candidate.get("priority", "?")
                    table = candidate.get("table", "?")
                    column = candidate.get("column", "?")
                    lines.append(f"      [{priority}] {table}.{column}")
            else:
                lines.append("    Sources: None (no direct mapping)")

            lines.append("")

    # Normalization rules
    normalization = surv_data.get("normalization", {})
    if normalization and verbose:
        lines.append("Normalization Rules")
        for rule_name, rule_spec in normalization.items():
            if isinstance(rule_spec, dict):
                lines.append(f"  - {rule_name}")
                if "description" in rule_spec:
                    lines.append(f"    {rule_spec['description']}")
                if "example" in rule_spec:
                    lines.append(f"    Example: {rule_spec['example']}")
        lines.append("")

    # Summary statistics
    total_cols = len(mappings)
    cols_with_candidates = sum(1 for m in mappings.values() if m.get("candidates"))
    cols_no_candidates = total_cols - cols_with_candidates

    lines.append("Summary")
    lines.append(f"  Total columns: {total_cols}")
    lines.append(f"  With source mappings: {cols_with_candidates}")
    lines.append(f"  Without source mappings: {cols_no_candidates}")

    if strategies:
        lines.append(f"  Strategies defined: {len(strategies)}")

    return "\n".join(lines)
