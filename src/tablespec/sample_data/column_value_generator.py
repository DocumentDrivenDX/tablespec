"""Column value generation using priority cascade pattern."""

import logging
import random
from typing import Any

from tablespec import GXConstraintExtractor

try:
    from tablespec.inference.domain_types import DomainTypeRegistry
except ImportError:
    DomainTypeRegistry = None  # type: ignore[assignment,misc]

from .config import GenerationConfig
from .constraint_handlers import ConstraintHandlers
from .date_processing import convert_umf_format_to_strftime, extract_date_constraints
from .generators import HealthcareDataGenerators
from .registry import KeyRegistry


class ColumnValueGenerator:
    """Generates column values using a priority cascade pattern.

    This class handles the complex logic of generating appropriate values for table columns,
    following a priority cascade of different value generation strategies:

    1. Column equality constraints (must equal another column)
    2. GX strftime date format expectations
    3. GX value set constraints
    4. Domain type generators (registry-based)
    5. Sample values from UMF
    6. GX regex patterns
    7. Foreign key relationships
    8. Domain-specific patterns (email, NPI, ZIP, etc.)
    9. Sample value pattern matching
    10. Type-based generation
    11. Context-aware fallbacks

    Post-generation validation enforces:
    - Not-null constraints
    - Max length constraints
    - Unique-within-record constraints
    - Primary/unique key uniqueness
    """

    def __init__(
        self,
        gx_extractor: GXConstraintExtractor,
        domain_type_registry: Any,
        generators: HealthcareDataGenerators,
        key_registry: KeyRegistry,
        constraint_handlers: ConstraintHandlers,
        config: GenerationConfig,
        debug_logged_columns: set[tuple[str, str]],
    ) -> None:
        """Initialize the column value generator.

        Args:
            gx_extractor: Great Expectations constraint extractor
            domain_type_registry: Domain type registry for domain-specific generators
            generators: Healthcare data generators
            key_registry: Key registry for foreign key management
            constraint_handlers: Constraint handlers for validation
            config: Generation configuration
            debug_logged_columns: Set tracking (table, column) pairs for debug logging

        """
        self.gx_extractor = gx_extractor
        self.domain_type_registry = domain_type_registry
        self.generators = generators
        self.key_registry = key_registry
        self.constraint_handlers = constraint_handlers
        self.config = config
        self.debug_logged_columns = debug_logged_columns
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate_column_value(
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
        gx_expectations_cache: dict[str, dict[str, Any]],
        should_apply_equality_constraint_fn: Any,
        should_apply_unique_within_record_constraint_fn: Any,
        ensure_distinct_from_columns_fn: Any,
    ) -> str | int | float | bool | list[float] | None:
        """Generate appropriate value for a specific column using UMF metadata.

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
            gx_expectations_cache: Cache of loaded GX expectations
            should_apply_equality_constraint_fn: Function to check if equality constraint applies
            should_apply_unique_within_record_constraint_fn: Function to check if unique-within-record constraint applies
            ensure_distinct_from_columns_fn: Function to ensure value is distinct from other columns

        Returns:
            Generated value for the column

        """
        col_name = col["name"]
        col_name_lower = col_name.lower()
        key_type = col.get(
            "key_type"
        )  # primary, unique, foreign_one_to_one, foreign_one_to_many
        source = col.get("source", "data")  # data, filename, metadata

        # Check if column is part of any unique constraints
        is_in_unique_constraint = False
        unique_constraints = umf_data.get("unique_constraints", [])
        for constraint in unique_constraints:
            if col_name in constraint:
                is_in_unique_constraint = True
                break

        # Initialize generated_value
        generated_value = None

        # Handle filename-sourced columns - constant value per file
        if source == "filename":
            # In Phase 5 (single file generation), filename columns get a constant placeholder
            # In Phase 6+ (multi-file ingestion), these will be parsed from actual filenames

            # PRIORITY: Use pre-selected constant value if available
            if col_name in filename_column_values:
                return filename_column_values[col_name]

            # Fallback to column name patterns
            if col_name_lower in ["rundate", "run_date"]:
                return "2024-10-15"  # Placeholder date
            if col_name_lower in ["state"]:
                return "IL"
            if col_name_lower in ["program", "lob", "pbptype"]:
                return "MEDICAID"
            # Handle date fields - detect format from column name
            if "date" in col_name_lower or "file_date" in col_name_lower:
                # Check for explicit format hints in column name
                if "mmddyyyy" in col_name_lower:
                    return "10152024"  # MMDDYYYY format
                if "yyyymmdd" in col_name_lower:
                    return "20241015"  # YYYYMMDD format
                if "ddmmyyyy" in col_name_lower:
                    return "15102024"  # DDMMYYYY format
                # Default to YYYYMMDD if no explicit format hint
                return "20241015"
            # Handle time fields - generate HHMM format
            if "time" in col_name_lower or "file_time" in col_name_lower:
                return "1234"  # 4-digit time placeholder
            # Handle project/year fields - generate 4-digit number
            if "project" in col_name_lower or "year" in col_name_lower:
                return random.choice(["1001", "1002", "2024", "2025"])
            # Handle claim/file name fields - infer from context
            if "claim" in col_name_lower or "file" in col_name_lower:
                return random.choice(["Claims_File", "Data_File", "Source_File"])
            # Default: Generate generic value and warn
            # This allows generation to continue for non-critical tables
            self.logger.warning(
                f"{table_name}.{col_name}: No sample_values for filename column, using generic placeholder. "
                + "Add sample_values to column definition for better filenames."
            )
            return "GENERIC_FILE"

        # Initialize unique value tracker for this column if needed
        needs_uniqueness_tracking = (
            key_type in ["primary", "unique", "foreign_one_to_one"]
            or is_in_unique_constraint
        )
        if needs_uniqueness_tracking and col_name not in unique_value_trackers:
            unique_value_trackers[col_name] = set()

        # Debug logging for columns that commonly fail validation
        # Only log once per (table, column) pair to avoid excessive logging
        debug_columns = {
            "clientmemberid",
            "clientmbrid",
            "servicetype",
            "cm_referral",
            "assessmenttype",
            "lob",
            "mbr_st_1",
            "mbrst_1",
        }
        debug_key = (table_name, col_name)
        enable_debug = (
            col_name_lower in debug_columns
            and debug_key not in self.debug_logged_columns
        )
        if enable_debug:
            self.debug_logged_columns.add(debug_key)

        # PRIORITY 0: Check for column equality constraints (must equal another column)
        if col_name in column_equality_constraints:
            for constraint in column_equality_constraints[col_name]:
                other_col = constraint["column_B"]
                ignore_row_if = constraint.get("ignore_row_if", "never")

                # Check if the other column has already been generated
                if other_col in record:
                    other_value = record[other_col]

                    # Apply ignore_row_if logic
                    should_apply = should_apply_equality_constraint_fn(
                        record, col_name, other_col, ignore_row_if
                    )

                    if should_apply and other_value is not None:
                        if enable_debug:
                            self.logger.info(
                                f"DEBUG: {table_name}.{col_name} - Using equality constraint: {col_name} == {other_col} = {other_value}"
                            )
                        return other_value

        # CRITICAL: Check for not-null expectation from BOTH GX and UMF
        gx_expectations = gx_expectations_cache.get(table_name)
        is_not_null = False
        if gx_expectations:
            is_not_null = self.gx_extractor.is_column_not_null(
                gx_expectations, col_name
            )

        # Also check UMF nullable specification - if all LOBs are non-nullable, enforce not-null
        nullable = col.get("nullable", {})
        if not is_not_null and nullable:
            is_not_null = not any(
                nullable.values()
            )  # True if all LOBs are non-nullable

        if enable_debug and is_not_null:
            self.logger.info(
                f"DEBUG: {table_name}.{col_name} - Column has NOT NULL constraint"
            )

        # Also check for max_length constraint
        max_length = None
        if gx_expectations:
            max_length = self.gx_extractor.get_max_length_for_column(
                gx_expectations, col_name
            )
            if enable_debug and max_length:
                self.logger.info(
                    f"DEBUG: {table_name}.{col_name} - Column has max_length={max_length} constraint"
                )

        # PRIORITY 1: Check for GX strftime date format expectations - highest priority for dates
        if gx_expectations:
            strftime_format = self.gx_extractor.get_strftime_format_for_column(
                gx_expectations, col_name
            )
            if strftime_format:
                # Check if this is a birth date column
                if "birth" in col_name_lower or "dob" in col_name_lower:
                    date_value = self.generators.generate_birth_date(
                        date_format=strftime_format
                    )
                else:
                    # Try to extract date constraints from validation rules
                    date_constraints = extract_date_constraints(col_name, umf_data)
                    if date_constraints:
                        date_value = (
                            self.generators.generate_date_in_range_with_constraints(
                                min_date_str=date_constraints.get("min_value"),
                                max_date_str=date_constraints.get("max_value"),
                                date_format=strftime_format,
                            )
                        )
                    else:
                        date_value = self.generators.generate_date_in_range(
                            date_format=strftime_format
                        )
                if enable_debug:
                    self.logger.info(
                        f"DEBUG: {table_name}.{col_name} - Using GX strftime: {strftime_format} -> {date_value}"
                    )
                return date_value

        # PRIORITY 2: Check for GX value set constraints
        if gx_expectations:
            gx_constraints = self.gx_extractor.get_constraints_for_column(
                gx_expectations, col_name
            )
            if gx_constraints:
                gx_value = random.choice(gx_constraints)
                if enable_debug:
                    self.logger.info(
                        f"DEBUG: {table_name}.{col_name} - Using GX value_set: {gx_constraints} -> {gx_value}"
                    )
                else:
                    self.logger.debug(
                        f"Generated value for {table_name}.{col_name} using GX constraints: {gx_value}"
                    )
                return gx_value

        # PRIORITY 2.5: Check for foreign key relationships
        # For columns with key_type foreign_*, use registered primary keys from parent tables
        # This ensures child table rows reference actual values from parent tables
        if key_type and "foreign" in key_type:
            # Check registered primary keys first (these are actual values from parent tables)
            all_pk_values = []
            for pk_list in self.key_registry.primary_keys.values():
                all_pk_values.extend(pk_list)
            if all_pk_values:
                fk_value = random.choice(all_pk_values)
                generated_value = fk_value
                if enable_debug:
                    self.logger.info(
                        f"DEBUG: {table_name}.{col_name} - Using registered PK value (key_type={key_type}): {generated_value}"
                    )
        # Also check FK pool for columns in equivalence groups (without explicit key_type)
        if generated_value is None:
            fk_value = self.key_registry.foreign_key_manager.get_value_for_column(
                col_name
            )
            if fk_value is not None:
                generated_value = fk_value
                if enable_debug:
                    self.logger.info(
                        f"DEBUG: {table_name}.{col_name} - Using FK pool value: {generated_value}"
                    )

        # PRIORITY 3: Check for domain type and use registry-based generator
        # This provides reliable, maintainable generation for well-known domain types
        # Domain types should take precedence over generic regex patterns
        # Skip if we already have a value from FK pool
        domain_type = col.get("domain_type")
        if (
            domain_type
            and generated_value is None
            and self.domain_type_registry is not None
        ):
            try:
                # Get generator method name from domain type registry
                generator_method = (
                    self.domain_type_registry.get_sample_generator_method(domain_type)
                )
                if generator_method and hasattr(self.generators, generator_method):
                    # Check if UMF specifies a format (for date/time columns)
                    umf_format = col.get("format")
                    date_format = convert_umf_format_to_strftime(umf_format)

                    # Date-related generators accept date_format parameter
                    date_generator_methods = {
                        "generate_date_in_range",
                        "generate_birth_date",
                        "generate_service_date",
                        "generate_timestamp",
                    }

                    if date_format and generator_method in date_generator_methods:
                        # Pass UMF format to date generator
                        generated_value = getattr(self.generators, generator_method)(
                            date_format=date_format
                        )
                        if enable_debug:
                            self.logger.info(
                                f"DEBUG: {table_name}.{col_name} - Using domain type '{domain_type}' "
                                f"generator: {generator_method}(date_format='{date_format}') -> {generated_value}"
                            )
                    else:
                        # Call generator without format parameter
                        generated_value = getattr(self.generators, generator_method)()
                        if enable_debug:
                            self.logger.info(
                                f"DEBUG: {table_name}.{col_name} - Using domain type '{domain_type}' "
                                f"generator: {generator_method}() -> {generated_value}"
                            )

                    if not enable_debug:
                        self.logger.debug(
                            f"Generated value for {table_name}.{col_name} using domain type '{domain_type}': {generated_value}"
                        )
                    # Don't return early - let uniqueness enforcement run for primary/unique keys
            except Exception as e:
                # Domain type generation failed, log and fall through
                self.logger.debug(
                    f"Domain type generation failed for {table_name}.{col_name} (domain_type='{domain_type}'): {e}"
                )

        # PRIORITY 3.5: Check for explicit sample_values before GX regex patterns
        # This ensures user-provided sample values take precedence over regex-based generation
        # which can produce malformed data for complex patterns
        # Only use sample_values if we don't already have a value from domain type generator
        if generated_value is None and sample_values and len(sample_values) > 0:
            # Filter out description/comment values that are clearly not data
            valid_values = [
                v
                for v in sample_values
                if v
                and not any(
                    phrase in str(v).lower()
                    for phrase in ["sample", "example", "description", "format", "n/a"]
                )
            ]
            if valid_values:
                generated_value = random.choice(valid_values)
                if enable_debug:
                    self.logger.info(
                        f"DEBUG: {table_name}.{col_name} - Using sample_values: {valid_values} -> {generated_value}"
                    )
                else:
                    self.logger.debug(
                        f"Generated value for {table_name}.{col_name} using sample_values: {generated_value}"
                    )
                # Don't return early - let uniqueness enforcement run for primary/unique keys

        # PRIORITY 4: Check for GX regex patterns - generate values matching regex
        # This is now a fallback when no domain type is specified
        # Only use GX patterns if we don't already have a value from domain type or sample_values
        if generated_value is None and gx_expectations:
            regex_pattern = self.gx_extractor.get_regex_for_column(
                gx_expectations, col_name
            )
            if regex_pattern:
                # Special handling for datetime/timestamp patterns - use date generator
                # Common patterns: YYYY-MM-DD HH:MM:SS, MM/DD/YYYY, YYYY-MM-DD, YYYYMMDD
                datetime_patterns = [
                    (
                        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                        "%Y-%m-%d %H:%M:%S",
                    ),  # Timestamp
                    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),  # Date ISO format
                    (
                        r"^\(0\[1-9\]\|1\[0-2\]\)/\(0\[1-9\]\|\[12\]\[0-9\]\|3\[01\]\)/\\d{4}$",
                        "%m/%d/%Y",
                    ),  # MM/DD/YYYY with month/day validation
                    (r"^\d{2}/\d{2}/\d{4}$", "%m/%d/%Y"),  # MM/DD/YYYY simple
                    (r"^\d{8}$", "%Y%m%d"),  # YYYYMMDD
                    (r"^\d{4}\d{2}\d{2}$", "%Y%m%d"),  # YYYYMMDD explicit
                ]

                # Check if this is a date/datetime pattern
                for date_pattern, date_format in datetime_patterns:
                    # Normalize both patterns for comparison
                    normalized_input = regex_pattern.replace("\\", "")
                    normalized_date = date_pattern.replace("\\", "")
                    if normalized_input == normalized_date:
                        # Check if this is a birth date column
                        if "birth" in col_name_lower or "dob" in col_name_lower:
                            date_value = self.generators.generate_birth_date(
                                date_format=date_format
                            )
                        else:
                            # Try to extract date constraints from validation rules
                            date_constraints = extract_date_constraints(
                                col_name, umf_data
                            )
                            if date_constraints:
                                date_value = self.generators.generate_date_in_range_with_constraints(
                                    min_date_str=date_constraints.get("min_value"),
                                    max_date_str=date_constraints.get("max_value"),
                                    date_format=date_format,
                                )
                            else:
                                date_value = self.generators.generate_date_in_range(
                                    date_format=date_format
                                )
                        if enable_debug:
                            self.logger.info(
                                f"DEBUG: {table_name}.{col_name} - Using date generator for regex: {regex_pattern} -> {date_value}"
                            )
                        return date_value

                # Special handling for LOINC pattern - use dedicated generator for better uniqueness
                # LOINC regex: ^\d{1,7}-\d$ (up to 7 digits, hyphen, single check digit)
                loinc_pattern = r"^\d{1,7}-\d$"
                if regex_pattern.replace("\\", "") == loinc_pattern.replace("\\", ""):
                    loinc_value = self.generators.generate_loinc()
                    if enable_debug:
                        self.logger.info(
                            f"DEBUG: {table_name}.{col_name} - Using LOINC generator for regex: {regex_pattern} -> {loinc_value}"
                        )
                    return loinc_value

                # Special handling for ZIP code patterns - use dedicated generator
                # ZIP patterns: ^\d{5}$, ^\d{9}$, ^\d{5}-\d{4}$, ^(?:\d{5}-\d{4}|\d{9})$
                # These patterns indicate ZIP codes with optional +4 extension
                zip_patterns = [
                    r"^\d{5}$",  # 5-digit ZIP
                    r"^\d{9}$",  # 9-digit ZIP (no dash)
                    r"^\d{5}-\d{4}$",  # ZIP+4 format
                    r"^\(\?:\\d{5}-\\d{4}\|\\d{9}\)$",  # Alternation with non-capturing group
                    r"^\(\?:\\d{9}\|\\d{5}-\\d{4}\)$",  # Reverse order
                ]

                # Normalize regex for comparison (remove anchors, unescape backslashes)
                normalized_pattern = regex_pattern.strip("^$").replace("\\", "")
                for zip_pattern in zip_patterns:
                    normalized_zip = zip_pattern.strip("^$").replace("\\", "")
                    if normalized_pattern == normalized_zip:
                        zip_value = self.generators.generate_zip_code()
                        if enable_debug:
                            self.logger.info(
                                f"DEBUG: {table_name}.{col_name} - Using ZIP generator for regex: {regex_pattern} -> {zip_value}"
                            )
                        return zip_value

                # Use generic regex generator for other patterns
                regex_value = self.gx_extractor.generate_value_from_regex(regex_pattern)
                if enable_debug:
                    self.logger.info(
                        f"DEBUG: {table_name}.{col_name} - Using GX regex: {regex_pattern} -> {regex_value}"
                    )
                else:
                    self.logger.debug(
                        f"Generated value for {table_name}.{col_name} using GX regex pattern {regex_pattern}: {regex_value}"
                    )
                return regex_value

        if enable_debug:
            self.logger.info(
                f"DEBUG: {table_name}.{col_name} - No GX constraints found, falling back to default patterns"
            )

        # Check for foreign key relationships
        if "relationships" in umf_data and "incoming" in umf_data["relationships"]:
            for rel in umf_data["relationships"]["incoming"]:
                if rel.get("target_column", "").lower() == col_name_lower:
                    rel.get("source_table")
                    cardinality_info = rel.get("cardinality", {})
                    mandatory = cardinality_info.get("mandatory", False)
                    cardinality = cardinality_info.get("type", "one_to_many")

                    # Apply relationship density for optional relationships
                    # BUT: Never return None if column has not-null expectation
                    if (
                        not mandatory
                        and not is_not_null
                        and random.random() > self.config.relationship_density
                    ):
                        if enable_debug:
                            self.logger.info(
                                f"DEBUG: {table_name}.{col_name} - Skipping optional relationship (density check)"
                            )
                        return None

                    # Use the source column from the relationship as the key for the foreign key manager
                    source_column = rel.get("source_column", col_name)
                    fk_value = self.key_registry.get_foreign_key(
                        source_column, cardinality, mandatory
                    )
                    if fk_value is not None:
                        # Don't return early - let uniqueness enforcement run if needed
                        generated_value = fk_value
                        # Skip remaining FK checks since we found one
                        break

        # Note: FK pool check moved to PRIORITY 2.5 to ensure FK relationships
        # take precedence over domain type generators

        # PRIORITY 4: Domain-specific patterns (email, NPI, ZIP, etc)
        # Only apply domain patterns if we haven't found a value yet from FK pools
        if generated_value is None:
            # Email patterns - must come before generic patterns
            if "email" in col_name_lower:
                return self.generators.generate_email()

            # NPI patterns
            if "npi" in col_name_lower:
                return self.generators.generate_npi()

            # ZIP code patterns - handle zip, zipcode, mbrzip, etc.
            if "zip" in col_name_lower:
                return self.generators.generate_zip_code()

            # Note: LOINC generation now handled via GX regex pattern detection
            # at PRIORITY 3, avoiding hardcoded column name checks

            # Member ID patterns - removed hardcoded clientmemberid detection
            # All ID generation now driven by UMF key_type metadata
            if "govtid" in col_name_lower or "govt_id" in col_name_lower:
                lob = random.choice(self.generators.lobs)
                return self.generators.generate_govt_id(lob)

            # Service and status patterns
            if (
                "servicetype" in col_name_lower.replace("_", "")
                or "service_type" in col_name_lower
            ):
                return self.generators.generate_service_type()
            if "disposition" in col_name_lower and "status" in col_name_lower:
                return self.generators.generate_disposition_status()
            if "assessment" in col_name_lower and "type" in col_name_lower:
                return self.generators.generate_assessment_type()
            if "provider" in col_name_lower and "type" in col_name_lower:
                return self.generators.generate_provider_type()
            # PCP type pattern - generates IMP, P4Q, FUL for primary care provider types
            if "pcp_type" in col_name_lower or "pcptype" in col_name_lower:
                return self.generators.generate_pcp_type()

            # Vendor patterns
            if "vendor" in col_name_lower:
                return self.generators.generate_vendor_name()

            # Plan code patterns
            if (
                "plancode" in col_name_lower.replace("_", "")
                or "plan_code" in col_name_lower
            ):
                return self.generators.generate_plan_code()

            # Procedure and diagnosis codes
            if (
                "procedurecode" in col_name_lower.replace("_", "")
                or "proc_code" in col_name_lower
                or "cpt" in col_name_lower
            ):
                return self.generators.generate_procedure_code()
            if "hcpcs" in col_name_lower:
                return self.generators.generate_procedure_code("HCPCS")
            if ("icd" in col_name_lower or "diag" in col_name_lower) and (
                "code" in col_name_lower or col_name_lower.endswith("icd")
            ):
                return self.generators.generate_diagnosis_code()

            # Date patterns - ONLY apply if the column is actually a date/datetime type
            # Check col_type to avoid treating string columns with "_date" in name as dates
            is_date_type = col_type and any(
                date_keyword in col_type.upper()
                for date_keyword in ["DATE", "TIME", "TIMESTAMP"]
            )

            if is_date_type:
                # Get date format from UMF column definition, default to ISO format
                umf_format = col.get("format")
                date_format = convert_umf_format_to_strftime(umf_format) or "%Y-%m-%d"

                # Check for birth dates first
                if "birth" in col_name_lower or "dob" in col_name_lower:
                    return self.generators.generate_birth_date(date_format=date_format)

                if col_name_lower.endswith("_date") or col_name_lower.startswith(
                    "date"
                ):
                    # For other dates, try to extract min/max from validation rules
                    date_constraints = extract_date_constraints(col_name, umf_data)
                    if date_constraints:
                        return self.generators.generate_date_in_range_with_constraints(
                            min_date_str=date_constraints.get("min_value"),
                            max_date_str=date_constraints.get("max_value"),
                            date_format=date_format,
                        )
                    return self.generators.generate_date_in_range(
                        date_format=date_format
                    )

            # Name patterns - include PCP name variants (pcp_fname, pcp_lname)
            if (
                "firstname" in col_name_lower
                or "first_name" in col_name_lower
                or "pcp_fname" in col_name_lower
            ):
                return self.generators.generate_name()[0]
            if (
                "lastname" in col_name_lower
                or "last_name" in col_name_lower
                or "pcp_lname" in col_name_lower
            ):
                return self.generators.generate_name()[2]
            if "middlename" in col_name_lower or "middle_name" in col_name_lower:
                return self.generators.generate_name()[1]

            # Other domain patterns
            if col_name_lower == "gender":
                return random.choice(self.generators.genders)
            if col_name_lower.startswith("mbrst"):
                source_state_value = record.get("source_state")
                if source_state_value:
                    return source_state_value
                return random.choice(self.generators.states)
            if "state" in col_name_lower:
                return random.choice(self.generators.states)
            if "totalrank" in col_name_lower or "rank" in col_name_lower:
                return self.generators.generate_rank()
            if "raf" in col_name_lower or "risk" in col_name_lower:
                return self.generators.generate_risk_score()
            if "phone" in col_name_lower:
                return f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"
            # Address patterns - handle address, addr, mbraddr, etc.
            # Check for addr2 before addr1 to handle columns like MbrAddr2_1
            if "addr" in col_name_lower:
                if "addr2" in col_name_lower or (
                    "2" in col_name_lower and "addr1" not in col_name_lower
                ):
                    return self.generators.generate_address()["address_line2"]
                if "addr1" in col_name_lower or "1" in col_name_lower:
                    return self.generators.generate_address()["address_line1"]
            # City patterns - handle city, mbrcity, membercity, etc.
            if "city" in col_name_lower:
                return self.generators.generate_address()["city"]
            # County patterns - handle county, mbrcounty, etc.
            if "county" in col_name_lower:
                return self.generators.generate_address()["county"]

        # Generate based on sample values if available (only if not already set by FK pools)
        if generated_value is None and sample_values:
            # Filter out description/comment values
            valid_values = [
                v
                for v in sample_values
                if not any(
                    phrase in str(v).lower()
                    for phrase in ["sample", "example", "description", "format"]
                )
            ]

            if valid_values:
                if len(valid_values) > 1:
                    # Multiple values - treat as enumeration
                    generated_value = random.choice(valid_values)
                else:
                    # Single value - try to extract pattern and generate similar
                    single_value = str(valid_values[0])

                    # Try to detect and generate from patterns
                    # Pattern: AL98765432101 (2 letters + 11 digits - ClientMemberId pattern)
                    if (
                        len(single_value) == 13
                        and single_value[:2].isalpha()
                        and single_value[2:].isdigit()
                    ):
                        letters = "".join(
                            random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                            for _ in range(2)
                        )
                        digits = "".join(str(random.randint(0, 9)) for _ in range(11))
                        generated_value = f"{letters}{digits}"
                    # Pattern: Alphanumeric codes (e.g., "H1234", "PCP01")
                    elif (
                        3 <= len(single_value) <= 10
                        and any(c.isalpha() for c in single_value)
                        and any(c.isdigit() for c in single_value)
                    ):
                        # Extract pattern - letters followed by digits or mixed
                        alpha_positions = [
                            i for i, c in enumerate(single_value) if c.isalpha()
                        ]
                        digit_positions = [
                            i for i, c in enumerate(single_value) if c.isdigit()
                        ]
                        if alpha_positions and digit_positions:
                            # Generate similar pattern
                            result = [""] * len(single_value)
                            for pos in alpha_positions:
                                result[pos] = random.choice(
                                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                                )
                            for pos in digit_positions:
                                result[pos] = str(random.randint(0, 9))
                            # Handle any special characters
                            for i, c in enumerate(single_value):
                                if not c.isalnum():
                                    result[i] = c  # Keep special chars like hyphens
                            generated_value = "".join(result)
                        else:
                            # Use as-is if pattern unclear
                            generated_value = single_value
                    # Pattern: Date-like strings (2023-11-14, 09/18/2024)
                    elif any(sep in single_value for sep in ["-", "/"]):
                        # Check if this is a birth date column
                        is_birth_date = (
                            "birth" in col_name_lower or "dob" in col_name_lower
                        )

                        if "/" in single_value and len(single_value.split("/")) == 3:
                            # MM/DD/YYYY format
                            if is_birth_date:
                                generated_value = self.generators.generate_birth_date(
                                    date_format="%m/%d/%Y"
                                )
                            else:
                                date_constraints = extract_date_constraints(
                                    col_name, umf_data
                                )
                                if date_constraints:
                                    generated_value = self.generators.generate_date_in_range_with_constraints(
                                        min_date_str=date_constraints.get("min_value"),
                                        max_date_str=date_constraints.get("max_value"),
                                        date_format="%m/%d/%Y",
                                    )
                                else:
                                    generated_value = (
                                        self.generators.generate_date_in_range(
                                            date_format="%m/%d/%Y"
                                        )
                                    )
                        elif "-" in single_value and len(single_value.split("-")) == 3:
                            parts = single_value.split("-")
                            if len(parts[0]) == 4:  # YYYY-MM-DD
                                if is_birth_date:
                                    generated_value = (
                                        self.generators.generate_birth_date(
                                            date_format="%Y-%m-%d"
                                        )
                                    )
                                else:
                                    date_constraints = extract_date_constraints(
                                        col_name, umf_data
                                    )
                                    if date_constraints:
                                        generated_value = self.generators.generate_date_in_range_with_constraints(
                                            min_date_str=date_constraints.get(
                                                "min_value"
                                            ),
                                            max_date_str=date_constraints.get(
                                                "max_value"
                                            ),
                                            date_format="%Y-%m-%d",
                                        )
                                    else:
                                        generated_value = (
                                            self.generators.generate_date_in_range(
                                                date_format="%Y-%m-%d"
                                            )
                                        )
                            elif is_birth_date:
                                generated_value = self.generators.generate_birth_date(
                                    date_format="%m-%d-%Y"
                                )
                            else:
                                date_constraints = extract_date_constraints(
                                    col_name, umf_data
                                )
                                if date_constraints:
                                    generated_value = self.generators.generate_date_in_range_with_constraints(
                                        min_date_str=date_constraints.get("min_value"),
                                        max_date_str=date_constraints.get("max_value"),
                                        date_format="%m-%d-%Y",
                                    )
                                else:
                                    generated_value = (
                                        self.generators.generate_date_in_range(
                                            date_format="%m-%d-%Y"
                                        )
                                    )
                        else:
                            generated_value = single_value
                    else:
                        # For other single values, use as-is (constants)
                        generated_value = single_value

        # Generate based on data type if no sample value was used
        # Use Spark native types: STRING, INTEGER, DECIMAL, DOUBLE, FLOAT, DATE, TIMESTAMP, BOOLEAN
        # Also handle UMF type names like DateType, TimestampType, IntegerType, DecimalType etc.
        if generated_value is None:
            col_type_upper = col_type.upper()
            # Handle both "INTEGER" and "IntegerType" formats
            if col_type_upper in ("INTEGER", "INTEGERTYPE", "INT", "LONGTYPE", "LONG"):
                generated_value = random.randint(1, 1000)
            # Handle both "DECIMAL" and "DecimalType" formats (also DECIMAL(p,s))
            elif (
                col_type_upper.startswith("DECIMAL") or col_type_upper == "DECIMALTYPE"
            ):
                generated_value = round(random.uniform(0, 100), 2)
            # Handle DOUBLE and FLOAT types
            elif col_type_upper in ("DOUBLE", "DOUBLETYPE", "FLOAT", "FLOATTYPE"):
                generated_value = round(random.uniform(0, 1000), 4)
            elif col_type_upper in ("DATE", "DATETYPE"):
                # Get date format from UMF column definition, default to ISO format
                umf_format = col.get("format")
                date_format = convert_umf_format_to_strftime(umf_format) or "%Y-%m-%d"

                # Check for birth dates first
                if "birth" in col_name_lower:
                    generated_value = self.generators.generate_birth_date(
                        date_format=date_format
                    )
                else:
                    # Try to extract date constraints from validation rules
                    date_constraints = extract_date_constraints(col_name, umf_data)
                    if date_constraints:
                        generated_value = (
                            self.generators.generate_date_in_range_with_constraints(
                                min_date_str=date_constraints.get("min_value"),
                                max_date_str=date_constraints.get("max_value"),
                                date_format=date_format,
                            )
                        )
                    else:
                        generated_value = self.generators.generate_date_in_range(
                            date_format=date_format
                        )
            elif col_type_upper in ("TIMESTAMP", "TIMESTAMPTYPE"):
                # Get timestamp format from UMF column definition, default to ISO format with time
                umf_format = col.get("format")
                date_format = (
                    convert_umf_format_to_strftime(umf_format) or "%Y-%m-%d %H:%M:%S"
                )

                # Check for birth dates first
                if "birth" in col_name_lower:
                    generated_value = self.generators.generate_birth_date(
                        date_format=date_format
                    )
                else:
                    # Try to extract date constraints from validation rules
                    date_constraints = extract_date_constraints(col_name, umf_data)
                    if date_constraints:
                        generated_value = (
                            self.generators.generate_date_in_range_with_constraints(
                                min_date_str=date_constraints.get("min_value"),
                                max_date_str=date_constraints.get("max_value"),
                                date_format=date_format,
                            )
                        )
                    else:
                        generated_value = self.generators.generate_date_in_range(
                            date_format=date_format
                        )
            elif col_type_upper.startswith("EMBEDDING"):
                dimension = col.get("dimension")
                if dimension is not None:
                    seed = f"{table_name}.{col_name}:{dimension}"
                    generated_value = self.generators.generate_embedding(
                        int(dimension), seed=seed
                    )
            elif col_type_upper == "BOOLEAN":
                generated_value = random.choice([True, False])
            # Default to STRING with context-aware fallback
            # Generate more meaningful defaults based on column name patterns
            elif "_type" in col_name_lower or col_name_lower.endswith("type"):
                # Generate type-like values
                generated_value = random.choice(
                    ["TYPE_A", "TYPE_B", "TYPE_C", "DEFAULT", "STANDARD", "CUSTOM"]
                )
            elif "_status" in col_name_lower or col_name_lower.endswith("status"):
                # Generate status-like values
                generated_value = random.choice(
                    [
                        "ACTIVE",
                        "INACTIVE",
                        "PENDING",
                        "COMPLETED",
                        "CANCELLED",
                        "SUSPENDED",
                    ]
                )
            elif "_code" in col_name_lower or col_name_lower.endswith("code"):
                # Generate code-like values
                prefix = random.choice(["A", "B", "C", "X", "Y", "Z"])
                generated_value = f"{prefix}{random.randint(100, 999)}"
            elif (
                "_flag" in col_name_lower
                or col_name_lower.endswith("flag")
                or "_ind" in col_name_lower
            ):
                # Generate flag/indicator values
                generated_value = random.choice(
                    ["Y", "N", "YES", "NO", "1", "0", "TRUE", "FALSE"]
                )
            elif "_reason" in col_name_lower or col_name_lower.endswith("reason"):
                # Generate reason-like values
                generated_value = random.choice(
                    [
                        "MEDICAL",
                        "ADMINISTRATIVE",
                        "CLINICAL",
                        "OPERATIONAL",
                        "OTHER",
                        "NOT_SPECIFIED",
                    ]
                )
            elif "_category" in col_name_lower or col_name_lower.endswith("category"):
                # Generate category-like values
                generated_value = random.choice(
                    [
                        "CATEGORY_1",
                        "CATEGORY_2",
                        "CATEGORY_3",
                        "PRIMARY",
                        "SECONDARY",
                        "TERTIARY",
                    ]
                )
            elif "_result" in col_name_lower or col_name_lower.endswith("result"):
                # Generate result-like values
                generated_value = random.choice(
                    [
                        "POSITIVE",
                        "NEGATIVE",
                        "NORMAL",
                        "ABNORMAL",
                        "PENDING",
                        "INCONCLUSIVE",
                    ]
                )
            elif "description" in col_name_lower or "desc" in col_name_lower:
                # Generate description-like values
                generated_value = f"Description for item {random.randint(100, 999)}"
            elif "comment" in col_name_lower or "note" in col_name_lower:
                # Generate comment/note-like values
                generated_value = f"Note: Entry {random.randint(100, 999)}"
            elif "_id" in col_name_lower or col_name_lower.endswith("id"):
                # Generate ID-like values (not caught by other patterns)
                generated_value = f"ID{random.randint(100000, 999999)}"
            elif "_name" in col_name_lower and not any(
                x in col_name_lower for x in ["firstname", "lastname", "middlename"]
            ):
                # Generate generic name-like values
                generated_value = f"Entity_{random.randint(100, 999)}"
            else:
                # Final fallback - use a more descriptive pattern
                generated_value = f"VAL_{random.randint(1000, 9999)}"

        # Post-generation validation: Ensure not-null constraints are respected
        if generated_value is None and is_not_null:
            # Generate a fallback value based on Spark native types and UMF types
            col_type_upper = col_type.upper()
            # Handle both "INTEGER" and "IntegerType" formats
            if col_type_upper in ("INTEGER", "INTEGERTYPE", "INT", "LONGTYPE", "LONG"):
                generated_value = random.randint(1, 1000)
            # Handle both "DECIMAL" and "DecimalType" formats (also DECIMAL(p,s))
            elif (
                col_type_upper.startswith("DECIMAL") or col_type_upper == "DECIMALTYPE"
            ):
                generated_value = round(random.uniform(0, 100), 2)
            # Handle DOUBLE and FLOAT types
            elif col_type_upper in ("DOUBLE", "DOUBLETYPE", "FLOAT", "FLOATTYPE"):
                generated_value = round(random.uniform(0, 1000), 4)
            elif col_type_upper in ("DATE", "DATETYPE"):
                # Get date format from UMF column definition
                umf_format = col.get("format")
                date_format = convert_umf_format_to_strftime(umf_format) or "%Y-%m-%d"
                # Check for birth dates
                if "birth" in col_name_lower:
                    generated_value = self.generators.generate_birth_date(
                        date_format=date_format
                    )
                else:
                    generated_value = self.generators.generate_date_in_range(
                        date_format=date_format
                    )
            elif col_type_upper in ("TIMESTAMP", "TIMESTAMPTYPE"):
                # Get timestamp format from UMF column definition
                umf_format = col.get("format")
                date_format = (
                    convert_umf_format_to_strftime(umf_format) or "%Y-%m-%d %H:%M:%S"
                )
                # Check for birth dates
                if "birth" in col_name_lower:
                    generated_value = self.generators.generate_birth_date(
                        date_format=date_format
                    )
                else:
                    generated_value = self.generators.generate_date_in_range(
                        date_format=date_format
                    )
            elif col_type_upper == "BOOLEAN":
                generated_value = random.choice([True, False])
            else:
                generated_value = f"NotNull_{random.randint(1000, 9999)}"

            if enable_debug:
                self.logger.info(
                    f"DEBUG: {table_name}.{col_name} - Replaced None with fallback "
                    + f"due to not-null constraint: {generated_value}"
                )

        # Post-generation validation: Trim to max_length if needed
        if (
            isinstance(generated_value, str)
            and max_length
            and len(generated_value) > max_length
        ):
            original_value = generated_value
            generated_value = generated_value[:max_length]
            if enable_debug:
                self.logger.info(
                    f"DEBUG: {table_name}.{col_name} - Trimmed '{original_value}' to max_length {max_length}: '{generated_value}'"
                )

        # Post-generation validation: Enforce unique-within-record constraints
        # Ensure this column's value differs from other columns in the same constraint group
        for constraint in unique_within_record_constraints:
            constraint_columns = constraint["columns"]
            ignore_row_if = constraint.get("ignore_row_if", "never")

            if col_name in constraint_columns:
                # Check if constraint should be applied
                should_apply = should_apply_unique_within_record_constraint_fn(
                    record, constraint_columns, ignore_row_if
                )

                if should_apply:
                    # Ensure generated value differs from other columns in this group
                    generated_value = ensure_distinct_from_columns_fn(
                        generated_value,
                        record,
                        constraint_columns,
                        col_name,
                        enable_debug,
                    )

                    if enable_debug and generated_value is not None:
                        self.logger.info(
                            f"DEBUG: {table_name}.{col_name} - Applied unique-within-record constraint for columns {constraint_columns}"
                        )

        # Post-generation validation: Enforce uniqueness for primary/unique/one-to-one keys
        # Also enforce uniqueness for columns that are part of unique constraints
        needs_uniqueness = (
            key_type in ["primary", "unique", "foreign_one_to_one"]
            or is_in_unique_constraint
        )
        if needs_uniqueness and generated_value is not None:
            tracker = unique_value_trackers[col_name]
            max_attempts = 1000  # Prevent infinite loops

            # If value is duplicate, regenerate with suffix until unique
            attempt = 0
            original_value = generated_value
            while generated_value in tracker and attempt < max_attempts:
                attempt += 1
                # Add numeric suffix to make unique
                if isinstance(generated_value, str):
                    # Strip previous suffixes before adding new one
                    base_value = str(original_value).rsplit("_", 1)[0]
                    generated_value = f"{base_value}_{attempt}"
                elif isinstance(generated_value, (int, float)) and isinstance(
                    original_value, (int, float)
                ):
                    generated_value = original_value + attempt  # type: ignore[operator]
                else:
                    # For other types, convert to string and add suffix
                    generated_value = f"{original_value}_{attempt}"

            if attempt >= max_attempts:
                self.logger.error(
                    f"Failed to generate unique value for {table_name}.{col_name} "
                    + f"after {max_attempts} attempts (key_type={key_type})"
                )
                msg = f"Could not generate unique value for {col_name}"
                raise ValueError(msg)

            # Track the unique value
            tracker.add(generated_value)

            if attempt > 0 and enable_debug:
                self.logger.info(
                    f"DEBUG: {table_name}.{col_name} - Made value unique: {original_value} -> {generated_value} "
                    + f"(key_type={key_type}, attempt={attempt})"
                )

        return generated_value
