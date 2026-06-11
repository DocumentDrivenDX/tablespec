"""UMF Pydantic Models

Type-safe models for Universal Metadata Format (UMF) files.
Provides runtime validation and serialization/deserialization.
"""

import logging
import warnings
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Validation Stage Classification
# =============================================================================
# Validations run on Bronze.Raw (string data, schema/structure checks)
# Quality Checks run on Bronze.Ingested (typed data, value/business rule checks)
#
# "Shift-left" principle: Run as many validations as possible on RAW data
# to fail fast and catch issues before type conversion.

RAW_VALIDATION_TYPES: frozenset[str] = frozenset(
    {
        # Table-level schema checks
        "expect_table_columns_to_match_set",
        "expect_table_row_count_to_be_between",
        # String length checks
        "expect_column_value_lengths_to_be_between",
        # Pattern matching
        "expect_column_values_to_match_regex",
        "expect_column_values_to_not_match_regex",
        "expect_column_values_to_match_regex_list",
        # Type castability - validates strings can be parsed BEFORE type conversion
        "expect_column_values_to_cast_to_type",
        # Null/empty checks - catch missing data early (empty string, "NULL", etc.)
        "expect_column_values_to_not_be_null",
        "expect_column_values_to_be_null",
        # Date/time format - string format validation
        "expect_column_values_to_match_strftime_format",
        # Set membership - string comparison works fine
        "expect_column_values_to_be_in_set",
        "expect_column_values_to_not_be_in_set",
        "expect_column_distinct_values_to_be_in_set",
        "expect_column_distinct_values_to_contain_set",
        "expect_column_most_common_value_to_be_in_set",
        # Uniqueness - string equality works fine
        "expect_column_values_to_be_unique",
        "expect_compound_columns_to_be_unique",
        "expect_select_column_values_to_be_unique_within_record",
    }
)

# Redundant validations that shouldn't be generated (covered by schema/metadata)
REDUNDANT_VALIDATION_TYPES: frozenset[str] = frozenset(
    {
        # expect_column_to_exist is redundant - schema already defines columns
        "expect_column_to_exist",
        # expect_column_values_to_be_of_type is redundant - covered by data_type field
        "expect_column_values_to_be_of_type",
    }
)

# Only validations that truly require typed data (numeric/date comparisons)
INGESTED_QUALITY_CHECK_TYPES: frozenset[str] = frozenset(
    {
        # Numeric/date range checks - require type conversion for comparison
        "expect_column_values_to_be_between",
        # Cross-column comparisons - require typed comparison operators
        "expect_column_pair_values_a_to_be_greater_than_b",
        "expect_column_pair_values_to_be_equal",
        # Pending implementation - complex business rules
        "expect_validation_rule_pending_implementation",
        # Temporal completeness - detect missing time periods in date columns
        "expect_date_column_to_have_complete_periods",
        # Run-over-run comparison - detect changes between pipeline runs
        "expect_row_count_change_within_percent",
        "expect_column_distribution_stable",
        "expect_record_changes_within_limits",
    }
)


def classify_validation_type(
    expectation_type: str,
) -> Literal["raw", "ingested", "unknown"]:
    """Classify a validation expectation type as raw or ingested.

    Args:
        expectation_type: Great Expectations expectation type name

    Returns:
        "raw" if validation runs on Bronze.Raw
        "ingested" if validation runs on Bronze.Ingested (quality check)
        "unknown" if type is not recognized

    """
    if expectation_type in RAW_VALIDATION_TYPES:
        return "raw"
    if expectation_type in INGESTED_QUALITY_CHECK_TYPES:
        return "ingested"
    return "unknown"


class FilenamePattern(BaseModel):
    """Filename pattern for extracting metadata from filenames."""

    regex: str = Field(description="Regular expression with capture groups")
    captures: dict[int, str] = Field(
        description="Mapping from capture group index to column name "
        "(e.g., {1: 'source_vendor', 7: 'mode'})"
    )
    description: str | None = Field(
        default=None, description="Human-readable pattern description"
    )


class FileFormatSpec(BaseModel):
    """File format specification for data ingestion."""

    delimiter: str = Field(default="|", description="Field delimiter character")
    encoding: str = Field(default="utf-8", description="File encoding")
    header: bool = Field(default=True, description="Whether file has header row")
    quote_char: str | None = Field(
        default=None, description="Quote character for fields"
    )
    escape_char: str | None = Field(default=None, description="Escape character")
    null_value: str | None = Field(
        default=None, description="String representing NULL values"
    )
    skip_rows: int = Field(
        default=0, ge=0, description="Number of rows to skip at start"
    )
    comment_char: str | None = Field(
        default=None, description="Comment line prefix character"
    )
    filename_pattern: FilenamePattern | None = Field(
        default=None,
        description="Pattern for extracting metadata from filenames into table columns",
    )
    source_directory: str | None = Field(
        default=None,
        description="Subdirectory name to look for files in (when different from table name). "
        "Used when files for multiple tables are stored in the same folder.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_filename_pattern(cls, data: Any) -> Any:
        """Normalize flat filename_pattern structure to nested FilenamePattern object.

        Supports legacy YAML structure where captures is a sibling to filename_pattern:
        ```
        file_format:
          filename_pattern: "regex..."
          captures:
            '1': col1
        ```

        Converts to nested structure:
        ```
        file_format:
          filename_pattern:
            regex: "regex..."
            captures:
              1: col1
        ```
        """
        if not isinstance(data, dict):
            return data

        # Check if we have the flat structure (filename_pattern is a string)
        pattern = data.get("filename_pattern")
        captures = data.get("captures")

        if isinstance(pattern, str) and captures is not None:
            # Convert to nested structure
            data["filename_pattern"] = {
                "regex": pattern,
                "captures": {int(k): v for k, v in captures.items()},
            }
            # Remove flat captures field
            data.pop("captures", None)

        return data


# Backward compatibility alias
FileFormat = FileFormatSpec


# =============================================================================
# Source shape contract (FEAT-031 / ADR-015)
# =============================================================================
# A UMF may declare WHERE its rows come from via a discriminated ``source:``
# block. ``file_format`` remains the backward-compatible spelling for
# delimited flat files; ``UMF.effective_source()`` resolves the two without
# ever mutating the loaded document (legacy UMFs must round-trip byte-
# identically).


class DelimitedSource(FileFormatSpec):
    """Delimited flat-file source: ``kind: delimited`` + the FileFormatSpec fields.

    The ``source:`` spelling of :class:`FileFormatSpec`. ``path`` optionally
    pins the file (or directory) to read; readers that are handed a spec
    without a path receive it from the caller per file.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["delimited"] = "delimited"
    path: str | None = Field(
        default=None,
        description="Optional file or directory path to read. Usually supplied "
        "at runtime by the caller rather than declared in the UMF.",
    )


class ParquetSource(BaseModel):
    """Parquet source (model stub; reading lands with bead tablespec-61da147e)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["parquet"]
    path: str | None = Field(
        default=None,
        description="File or directory path of the parquet data to read.",
    )


class JdbcSource(BaseModel):
    """JDBC source (JDBC-01). Reading lands with bead tablespec-4b65c810.

    Credentials are never inlined: ``password_secret_ref`` names a secret in
    the runtime's secret store. A literal ``password`` field is rejected
    (``extra=\"forbid\"``).
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["jdbc"]
    url: str = Field(description="JDBC connection URL (jdbc:...)")
    dbtable: str | None = Field(
        default=None,
        description="Table (or subquery alias) to read. Mutually exclusive with 'query'.",
    )
    query: str | None = Field(
        default=None,
        description="SQL query to read. Mutually exclusive with 'dbtable'.",
    )
    driver: str | None = Field(
        default=None, description="JDBC driver class name override"
    )
    user: str | None = Field(default=None, description="Connection user name")
    password_secret_ref: str | None = Field(
        default=None,
        description="Reference to the connection password in the runtime secret "
        "store (e.g. a Databricks secret scope/key). Plaintext passwords are "
        "rejected by design.",
    )
    fetch_size: int | None = Field(
        default=None, ge=1, description="JDBC fetch size hint"
    )
    partition_column: str | None = Field(
        default=None, description="Numeric column used for partitioned reads"
    )
    lower_bound: int | str | None = Field(
        default=None, description="Partitioned-read lower bound"
    )
    upper_bound: int | str | None = Field(
        default=None, description="Partitioned-read upper bound"
    )
    num_partitions: int | None = Field(
        default=None, ge=1, description="Number of partitions for parallel reads"
    )

    @model_validator(mode="after")
    def validate_dbtable_xor_query(self) -> Self:
        """Require exactly one of dbtable / query."""
        if (self.dbtable is None) == (self.query is None):
            msg = "JdbcSource requires exactly one of 'dbtable' or 'query'"
            raise ValueError(msg)
        return self


SourceSpec = Annotated[
    DelimitedSource | ParquetSource | JdbcSource,
    Field(discriminator="kind"),
]

#: Source kinds whose RAW stage lands NATIVE-TYPED data (FEAT-031 SRC-04 /
#: ADR-015): ``parquet`` and ``jdbc``. ``delimited`` keeps the proven
#: all-STRING raw landing (ADR-007). Suite composition consults this to keep
#: string-shape raw checks (length/regex/strftime/castability) off typed raw
#: (SUITE-01/SUITE-02) -- see ``tablespec.gx_baseline``.
TYPED_RAW_SOURCE_KINDS: frozenset[str] = frozenset({"jdbc", "parquet"})


class Nullable(BaseModel):
    """Nullable configuration per context (e.g., Line of Business).

    Accepts arbitrary context keys with boolean values. Common healthcare
    contexts include MD (Medicaid), MP (Medicare Part D), ME (Medicare),
    but any domain-specific keys are supported.

    Examples:
        Nullable(MD=False, MP=False, ME=False)      # Healthcare LOBs
        Nullable(US=False, EU=True)                  # Regional contexts
        Nullable(production=False, staging=True)      # Environment contexts
    """

    model_config = ConfigDict(extra="allow")


class JoinViaSpec(BaseModel):
    """Specification for joining through an intermediary lookup table.

    Used when the source table's join key doesn't directly match the target's primary key.
    For example, when a truncated key needs to be resolved through an intermediary
    table to get the full identifier.
    """

    lookup_table: str = Field(
        description="Intermediary table to join through (e.g., 'datawarehouse')"
    )
    source_key: str = Field(
        description="Key column in the base table (e.g., 'client_member_id')"
    )
    lookup_key: str = Field(
        description="Key column in lookup table that matches source_key (e.g., 'member_id')"
    )
    target_key: str = Field(
        description="Key column that links lookup table to source table (e.g., 'insurance_policy')"
    )


class DerivationCandidate(BaseModel):
    """Source column candidate for survivorship derivation."""

    table: str = Field(
        description="Source table name (supports qualified refs: 'pipeline.table' or bare 'table'). "
        "Special value 'intermediate' indicates expression uses columns from intermediate "
        "pre-aggregation views already joined into the base context "
        "(no separate table JOIN created)."
    )
    column: str | None = Field(
        default=None,
        description="Source column name (optional if expression is provided)",
    )
    expression: str | None = Field(
        default=None,
        description="SQL expression for deriving value (e.g., 'CONCAT_WS(\" \", fname, lname)'). "
        "Use instead of column for computed values.",
    )
    priority: int = Field(ge=1, description="Priority order (1 = highest priority)")
    reason: str | None = Field(
        default=None,
        description="Explanation of why this source was selected and its priority",
    )
    join_filter: str | None = Field(
        default=None,
        description="SQL WHERE clause for filtering this table join (e.g., 'pcp_type = \"P4Q\"'). "
        "Used when joining same table multiple times with different filters.",
    )
    table_instance: str | None = Field(
        default=None,
        description="Unique alias for this table+filter combination (e.g., 'pcp_assigned', 'pcp_imputed'). "
        "Required when joining same table multiple times with different filters to disambiguate joins.",
    )
    join_via: JoinViaSpec | None = Field(
        default=None,
        description="Specification for joining through an intermediary lookup table. "
        "Used when the source table's key doesn't directly match the target's primary key.",
    )
    order_by: list[str] | None = Field(
        default=None,
        description="Columns for window function ORDER BY (all DESC). When specified, uses "
        "ROW_NUMBER() window function instead of GROUP BY aggregation to get the full row "
        "with max value. E.g., ['result_approval_date', 'meta_snapshot_dt'] for max row by "
        "date then file timestamp.",
    )
    row_filter: str | None = Field(
        default=None,
        description="SQL WHERE clause to filter source rows before aggregation. "
        "E.g., 'test_name = \"Glyco HGB A1C\" AND result IS NOT NULL'. "
        "Used with window functions to pre-filter qualifying records.",
    )
    select_columns: list[str] | None = Field(
        default=None,
        description="Additional columns to include in the aggregation view output. "
        "Used with window functions to preserve traceability columns like result value, "
        "meta_source_name, loinc code, etc. "
        "E.g., ['result', 'meta_source_name', 'meta_snapshot_dt'].",
    )

    @model_validator(mode="after")
    def validate_column_or_expression(self) -> "DerivationCandidate":
        """Ensure either column or expression is provided (but not necessarily both)."""
        if self.column is None and self.expression is None:
            msg = "Either 'column' or 'expression' must be provided"
            raise ValueError(msg)
        return self


class Survivorship(BaseModel):
    """Survivorship strategy for multi-source column derivation."""

    strategy: str = Field(
        description="Survivorship strategy (e.g., 'highest_priority', 'most_recent', 'longest_value')"
    )
    explanation: str = Field(
        description="Comprehensive explanation of mapping strategy, source selection/rejection reasoning, "
        "candidates examined, business rules applied, and fallback behavior",
    )
    default_value: str | int | float | bool | None = Field(
        default=None,
        description="Default value to use when no source data is available or all candidates are null. "
        "Extracted from target column description (e.g., 'default to 0', 'Default it to IHA').",
    )
    default_condition: str | None = Field(
        default=None,
        description="Condition or context for when the default value should be applied. "
        "Extracted from target column description "
        "(e.g., 'until assessment is completed', 'when not available').",
    )


class UMFColumnDerivation(BaseModel):
    """Column derivation metadata for multi-source survivorship.

    Used when a column in a generated table is derived from multiple source tables,
    requiring survivorship logic to choose the best value.

    Note: Either candidates, survivorship, or strategy must be present.
    Enterprise-only fields may have survivorship metadata without candidates.
    Primary key columns use strategy: primary_key without candidates.
    """

    strategy: str | None = Field(
        default=None,
        description="Derivation strategy for special column types. Use 'primary_key' for "
        "columns that should be derived from the base table's primary key column, or "
        "'base_column' for columns that come directly from the base table.",
    )
    explanation: str | None = Field(
        default=None,
        description="Human-readable explanation of the derivation logic for documentation.",
    )
    candidates: list[DerivationCandidate] | None = Field(
        default=None,
        min_length=1,
        description="Source columns this field can be derived from, ordered by priority. "
        "May be omitted for enterprise-only fields that have no source candidates.",
    )
    survivorship: Survivorship | None = Field(
        default=None,
        description="Survivorship strategy for selecting among candidates",
    )

    @model_validator(mode="after")
    def validate_candidates_not_empty(self) -> "UMFColumnDerivation":
        """Ensure candidates list is not empty if present.

        An empty candidates list indicates a configuration error:
        - If column has source candidates, list them
        - If column has NO source candidates, omit derivation section entirely

        This prevents SQL generation bugs where empty candidates with default_value
        could be misinterpreted as literal string values.
        """
        if self.candidates is not None and len(self.candidates) == 0:
            msg = (
                "Derivation candidates list cannot be empty. "
                "If column has no source candidates, omit the entire derivation section. "
                "Columns without derivation will generate CAST(NULL AS type) in SQL."
            )
            raise ValueError(msg)
        return self


class UMFColumn(BaseModel):
    """UMF Column definition."""

    name: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=128)
    ] = Field(description="Column name")
    canonical_name: str | None = Field(
        default=None,
        description="Canonical column name from source specifications (original case, any format). "
        "Used for input/output file headers. Can contain spaces, special characters, etc. "
        "If not provided, defaults to name.",
    )
    aliases: list[str] | None = Field(
        default=None,
        description="Alternative names for this column (e.g., variations in spelling, case, or abbreviations). "
        "Used for resolving column name mismatches when mapping between different data sources.",
    )
    data_type: str = Field(
        description="Column data type",
        pattern=r"^(VARCHAR|DECIMAL|INTEGER|DATE|DATETIME|TIMESTAMP|BOOLEAN|TEXT|CHAR|FLOAT)$",
    )
    position: str | None = Field(
        default=None, description="Excel column position or identifier"
    )
    description: str | None = Field(default=None, description="Column description")
    nullable: Nullable | None = Field(default=None, description="Nullability by LOB")
    sample_values: list[str] | None = Field(
        default=None, description="Sample values for the column"
    )
    length: int | None = Field(
        default=None, ge=1, description="Maximum length for VARCHAR columns"
    )
    precision: int | None = Field(
        default=None, ge=1, description="Precision for DECIMAL columns"
    )
    scale: int | None = Field(
        default=None, ge=0, description="Scale for DECIMAL columns"
    )
    title: str | None = Field(default=None, description="Column title")
    format: str | None = Field(
        default=None,
        description="Unstructured format pattern or example from source specification. "
        "May contain date patterns (YYYY-MM-DD), value enumerations (M, F, U), "
        "structural patterns (State_LOB), or example values ('40', '1.85'). "
        "This field preserves vendor documentation as-is and requires "
        "context-aware interpretation based on the data_type and column purpose.",
    )
    fallback_formats: list[str] | None = Field(
        default=None,
        description="Alternative date/timestamp formats to try if primary format fails. "
        "Used when source data has mixed format conventions (e.g., M/D/YYYY and MM-DD-YYYY). "
        "Formats are tried in order after the primary format fails.",
    )
    notes: list[str] | None = Field(
        default=None,
        description="Additional notes or business rules from source specification. "
        "Contains unstructured documentation that provides context for the column.",
    )
    source: str | None = Field(
        default=None,
        description="Source of column value: 'data' (from file content), "
        "'filename' (parsed from filename), 'metadata' (from ingestion metadata), "
        "or 'derived' (computed at runtime in Silver/Gold layers)",
        pattern=r"^(data|filename|metadata|derived)$",
    )
    key_type: str | None = Field(
        default=None,
        description="Key type for constraint-aware generation: 'primary', 'unique', "
        "'foreign_one_to_one', or 'foreign_one_to_many'",
        pattern=r"^(primary|unique|foreign_one_to_one|foreign_one_to_many)$",
    )
    exclude_from_change_detection: bool = Field(
        default=False,
        description="When True, exclude this column from change detection hash. "
        "Use for columns whose values change every run (e.g., rundate) but should not "
        "trigger a record to be treated as 'changed'.",
    )
    reporting_requirement: str | None = Field(
        default=None,
        description="Reporting requirement classification: 'R' (Required), 'O' (Optional), 'S' (Suggested)",
        pattern=r"^(R|O|S)$",
    )
    derived_from: str | None = Field(
        default=None,
        description="DEPRECATED: Use 'derivation' field instead. "
        "Source column name when this column is derived from another column "
        "(e.g., PBPType derived from source_lob)",
    )
    derivation_mapping: dict[str, str] | None = Field(
        default=None,
        description="DEPRECATED: Use 'derivation' field instead. "
        "Value mapping for derivation: {source_value: derived_value} "
        "(e.g., {'MD': 'MEDICAID', 'ME': 'MEDICARE'})",
    )
    derivation_expression: str | None = Field(
        default=None,
        description="DEPRECATED: Use 'derivation' field instead. "
        "Python expression for complex derivations.",
    )
    domain_type: str | None = Field(
        default=None,
        description="Domain type classification (e.g., 'us_state_code', 'email', 'phone_number', 'member_id'). "
        "Used to apply standard validation rules, sample data generators, and format patterns. "
        "Inferred during spec generation based on column name and metadata.",
    )
    derivation: UMFColumnDerivation | None = Field(
        default=None,
        description="Multi-source derivation metadata with survivorship strategy. "
        "Specifies candidate source columns and logic for selecting the best value. "
        "Used for generated tables that consolidate data from multiple sources.",
    )
    provenance_policy: str | None = Field(
        default=None,
        description="Data provenance policy for survivorship mapping: "
        "'enterprise_only' (never use outreach files), "
        "'enterprise_preferred' (prefer enterprise; use outreach as fallback), "
        "'outreach_only' (only use outreach files), "
        "'survivorship' (standard multi-source logic)",
        pattern=r"^(enterprise_only|enterprise_preferred|outreach_only|survivorship)$",
    )
    provenance_notes: str | None = Field(
        default=None,
        description="Human-readable explanation of provenance policy and data source expectations",
    )
    pivot_field: bool | None = Field(
        default=None,
        description="Whether this field is part of a numbered pivot sequence (e.g., GAP1, GAP2, GAP3)",
    )
    pivot_source_table: str | None = Field(
        default=None,
        description="Source table for pivot field (e.g., 'outreach_list_gaps' for GAP1, GAP2, etc.)",
    )
    pivot_source_column: str | None = Field(
        default=None,
        description="Source column name to pivot from (e.g., 'quality_gap_group' for GAP fields)",
    )
    pivot_index: int | None = Field(
        default=None,
        ge=1,
        description="Position in the pivot sequence (e.g., 1 for GAP1, 2 for GAP2, etc.)",
    )
    pivot_max_count: int | None = Field(
        default=None,
        ge=1,
        description="Maximum number of pivot fields in the sequence (e.g., 6 for GAP1-GAP6)",
    )
    default: str | int | float | bool | None = Field(
        default=None,
        description="Default value to use for this column when no data is provided or value is null. "
        "Commonly used in disposition tracking and status fields.",
    )
    profiling: dict[str, Any] | None = Field(
        default=None,
        description="Profiling metadata for data quality expectations "
        "(e.g., completeness, approximate_num_distinct). "
        "Used to generate profiling-based Great Expectations constraints.",
    )
    null_output_value: str | None = Field(
        default=None,
        description="String value to use when rendering NULL values in output files. "
        "When specified, NULL values are replaced with this string during output formatting. "
        "When not specified, NULL values are rendered according to the CSV writer's "
        "nullValue option (empty string by default). "
        "Example: 'NA', 'N/A', 'NULL', '9999-12-31'",
    )
    preserve_literal_null: bool = Field(
        default=False,
        description="If True, the string 'NULL' (case-insensitive) is preserved as a "
        "literal string value during ingestion. If False (default), 'NULL' "
        "strings are converted to SQL NULL. Use this for columns where 'NULL' "
        "is a valid data value (e.g., someone's actual last name is 'NULL').",
    )

    @field_validator("length")
    @classmethod
    def length_required_for_varchar(cls, v, info) -> int | None:
        """Validate that VARCHAR columns have length specified."""
        if info.data.get("data_type") == "VARCHAR" and v is None:
            # Warning only - not a hard error for backward compatibility
            pass
        return v

    @field_validator("precision")
    @classmethod
    def precision_recommended_for_decimal(cls, v, info) -> int | None:
        """Validate that DECIMAL columns should have precision specified."""
        if info.data.get("data_type") == "DECIMAL" and v is None:
            # Warning only - not a hard error for backward compatibility
            pass
        return v

    def is_nullable_for_all_contexts(self) -> bool:
        """Check if column is nullable across all contexts.

        Returns True if nullable for all contexts or if nullable is not specified.
        Returns False if required (non-nullable) for any context.
        """
        if self.nullable is None:
            return True  # Default to nullable if not specified
        if isinstance(self.nullable, bool):
            return self.nullable
        if isinstance(self.nullable, dict):
            return all(self.nullable.values())
        # Nullable model instance — iterate all set fields (extra fields included)
        fields = self.nullable.model_dump(exclude_none=True)
        if not fields:
            return True  # No contexts defined = nullable by default
        return all(fields.values())

    def is_required_for_any_context(self) -> bool:
        """Check if column is required (non-nullable) for any context.

        Returns True if required for at least one context.
        Returns False if nullable for all contexts.
        """
        return not self.is_nullable_for_all_contexts()

    @model_validator(mode="after")
    def validate_domain_type_compatibility(self) -> Self:
        """Validate that domain_type is compatible with data_type.

        Uses DomainTypeRegistry to check if the domain type's expected base type
        is compatible with the column's declared data_type. String types (VARCHAR,
        TEXT, CHAR) are allowed if a format is specified (Bronze layer pattern where
        strings will be cast to the target type).

        Raises:
            ValueError: If domain_type is incompatible with data_type
        """
        if self.domain_type is None:
            return self

        try:
            from tablespec.inference.domain_types import DomainTypeRegistry

            registry = DomainTypeRegistry()
        except (ImportError, FileNotFoundError):
            # Registry not available - skip validation
            return self

        expected = registry.get_expected_base_type(self.domain_type)
        if expected is None:
            # No type constraint for this domain type (e.g., email, unknown types)
            return self

        # Map UMF data_type to compatibility groups
        umf_type = self.data_type.upper()
        string_types = {"VARCHAR", "TEXT", "CHAR"}

        # If data_type is a string type and format is specified, allow it
        # (Bronze layer pattern: string columns with format can be cast to target type)
        if umf_type in string_types and self.format is not None:
            return self

        # Check compatibility between expected base type and UMF data_type
        compatible = False
        if expected == "DATE":
            compatible = umf_type in ("DATE", "DATETIME")
        elif expected == "TIMESTAMP":
            compatible = umf_type in ("DATETIME",)
        elif expected == "INTEGER":
            compatible = umf_type in ("INTEGER",)
        elif expected == "STRING":
            compatible = umf_type in string_types
        elif expected == "BOOLEAN":
            compatible = umf_type in ("BOOLEAN",)
        else:
            # Exact match for unknown expected types
            compatible = umf_type == expected

        if not compatible:
            msg = (
                f"Incompatible domain_type '{self.domain_type}' for column '{self.name}' "
                f"with data_type '{self.data_type}'. "
                f"Domain type '{self.domain_type}' expects {expected}-compatible type."
            )
            raise ValueError(msg)

        return self


class ValidationRule(BaseModel):
    """Individual validation rule."""

    rule_type: str = Field(description="Type of validation rule")
    description: str = Field(description="Rule description")
    severity: str = Field(
        description="Rule severity", pattern=r"^(error|warning|info)$"
    )
    parameters: dict[str, Any] | None = Field(
        default=None, description="Rule parameters"
    )


class ValidationRules(BaseModel):
    """Validation rules for UMF table."""

    table_level: list[ValidationRule] | None = Field(
        default=None, description="Table-level validation rules"
    )
    column_level: dict[str, list[ValidationRule]] | None = Field(
        default=None, description="Column-level validation rules"
    )
    expectations: list[dict[str, Any]] | None = Field(
        default=None, description="GX-style expectation list (legacy/loader format)"
    )
    pending_expectations: list[dict[str, Any]] | None = Field(
        default=None, description="Expectations pending implementation"
    )


class QualityCheck(BaseModel):
    """Single data quality check executed on typed/ingested data.

    Quality checks run on typed data AFTER type conversion.
    They check data values, business rules, and cross-column constraints.

    See INGESTED_QUALITY_CHECK_TYPES for allowed expectation types.
    """

    expectation: dict[str, Any] = Field(
        description="Great Expectations expectation configuration (type + kwargs + meta)"
    )
    severity: Literal["critical", "error", "warning", "info"] = Field(
        description="Severity level: critical (halt), error (fail), warning (log), info (report)"
    )
    blocking: bool = Field(
        default=False,
        description="If True, pipeline execution halts when this check fails. Default: False (non-blocking)",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of what this check validates",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for grouping/filtering checks (e.g., ['business_rule', 'lob'])",
    )


class QualityChecks(BaseModel):
    """Data quality checks executed on typed/ingested data.

    These checks run on typed data AFTER type conversion.
    They validate data values, business rules, and relationships.

    See INGESTED_QUALITY_CHECK_TYPES for allowed check types.

    For schema/structure checks on raw strings, use validation_rules instead.
    """

    checks: list[QualityCheck] = Field(
        default_factory=list,
        description="List of quality checks to execute on ingested data",
    )
    thresholds: dict[str, Any] | None = Field(
        default=None,
        description="Aggregate quality thresholds (e.g., max_critical_failure_percent: 5.0)",
    )
    alert_config: dict[str, Any] | None = Field(
        default=None,
        description="Alerting configuration (channels, recipients, threshold_breach_only)",
    )

    @model_validator(mode="after")
    def warn_misclassified_checks(self) -> Self:
        """Warn if quality_checks contain raw-stage types that belong in validation_rules."""
        if not self.checks:
            return self

        misclassified = []
        for check in self.checks:
            exp_type = check.expectation.get("type", "")
            if exp_type in RAW_VALIDATION_TYPES:
                misclassified.append(exp_type)

        if misclassified:
            message = (
                "QualityChecks contains raw-stage expectations that should be in validation_rules: "
                f"{misclassified}"
            )
            warnings.warn(message, UserWarning, stacklevel=2)
            logger.debug(message)

        return self


class ForeignKey(BaseModel):
    """Foreign key relationship."""

    column: str = Field(description="Source column name")
    references_table: str = Field(description="Referenced table name")
    references_column: str = Field(description="Referenced column name")
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence score for relationship"
    )
    type: str | None = Field(
        default=None,
        description="Relationship type (e.g., 'foreign_key', 'reference')",
    )
    domain_context: str | None = Field(
        default=None,
        description="Healthcare/business domain context (e.g., 'member-provider relationship')",
    )

    # Legacy field support
    references: str | None = Field(
        default=None, description="Legacy format: table.column"
    )
    detection_method: str | None = Field(
        default=None, description="Method used to detect relationship"
    )

    # Cross-pipeline support
    cross_pipeline: bool = Field(
        default=False,
        description="Whether this FK references a table in a different pipeline",
    )
    references_pipeline: str | None = Field(
        default=None,
        description="Pipeline name for cross-pipeline references",
    )

    # Join behavior
    join_type: str | None = Field(
        default=None,
        description="SQL join type: 'left' (default) or 'inner'",
    )

    @field_validator("references_table", mode="before")
    @classmethod
    def parse_references_table(cls, v, info) -> str | None:
        """Parse table name from legacy references field."""
        if (
            v is None
            and info.data
            and "references" in info.data
            and info.data["references"]
        ):
            parts = info.data["references"].split(".")
            if len(parts) == 2:
                return parts[0]
        return v

    @field_validator("references_column", mode="before")
    @classmethod
    def parse_references_column(cls, v, info) -> str | None:
        """Parse column name from legacy references field."""
        if (
            v is None
            and info.data
            and "references" in info.data
            and info.data["references"]
        ):
            parts = info.data["references"].split(".")
            if len(parts) == 2:
                return parts[1]
        return v


class ReferencedBy(BaseModel):
    """Reverse foreign key relationship."""

    table: str = Field(description="Referencing table name")
    column: str = Field(description="Referenced column name")
    foreign_key_column: str = Field(description="Foreign key column name")
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Confidence score for relationship"
    )


class Index(BaseModel):
    """Database index definition."""

    name: str = Field(description="Index name")
    columns: list[str] = Field(description="Index columns")
    unique: bool = Field(default=False, description="Whether index is unique")
    description: str | None = Field(default=None, description="Index description")


class Cardinality(BaseModel):
    """Relationship cardinality specification."""

    type: str = Field(
        description="Cardinality type (e.g., many_to_one, one_to_many, one_to_one)"
    )
    notation: str = Field(description="Cardinality notation (e.g., 1:N, N:1, 1:1)")
    composite_key: bool = Field(
        default=False,
        description="Whether the relationship uses a composite key",
    )
    mandatory: bool = Field(
        default=False, description="Whether the relationship is mandatory"
    )
    source_multiplicity: str = Field(
        description="Source side multiplicity (e.g., '*', '1', '0..1')"
    )
    target_multiplicity: str = Field(
        description="Target side multiplicity (e.g., '*', '1', '0..1')"
    )
    pattern_matched: str | None = Field(
        default=None, description="Pattern used to infer cardinality"
    )
    reason: str | None = Field(
        default=None, description="Reason for cardinality assignment"
    )


class OutgoingRelationship(BaseModel):
    """Outgoing foreign key relationship to another table."""

    target_table: str = Field(
        description="Table that this table references "
        "(supports qualified refs: 'pipeline.table' or bare 'table')"
    )
    source_column: str = Field(
        description="Column in this table that references target table"
    )
    target_column: str = Field(description="Column in target table being referenced")
    type: str = Field(description="Relationship type (e.g., foreign_to_primary)")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score for relationship"
    )
    reasoning: str | None = Field(
        default=None, description="AI reasoning for relationship detection"
    )
    cardinality: Cardinality | None = Field(
        default=None, description="Cardinality specification for relationship"
    )


class IncomingRelationship(BaseModel):
    """Incoming foreign key relationship from another table."""

    source_table: str = Field(
        description="Table that references this table "
        "(supports qualified refs: 'pipeline.table' or bare 'table')"
    )
    source_column: str = Field(
        description="Column in source table that references this table"
    )
    target_column: str = Field(description="Column in this table being referenced")
    type: str = Field(description="Relationship type (e.g., foreign_to_foreign)")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score for relationship"
    )
    reasoning: str | None = Field(
        default=None, description="AI reasoning for relationship detection"
    )
    cardinality: Cardinality | None = Field(
        default=None, description="Cardinality specification for relationship"
    )


class RelationshipSummary(BaseModel):
    """Summary statistics for table relationships."""

    total_relationships: int = Field(ge=0, description="Total number of relationships")
    total_incoming: int = Field(ge=0, description="Number of incoming relationships")
    total_outgoing: int = Field(ge=0, description="Number of outgoing relationships")
    hub_score: float = Field(
        ge=0.0,
        description="Hub score indicating centrality in relationship graph",
    )


class Relationships(BaseModel):
    """Table relationships."""

    foreign_keys: list[ForeignKey] | None = Field(
        default=None, description="Foreign key relationships"
    )
    referenced_by: list[ReferencedBy] | None = Field(
        default=None, description="Reverse foreign key relationships"
    )
    indexes: list[Index] | None = Field(default=None, description="Database indexes")
    outgoing: list[OutgoingRelationship] | None = Field(
        default=None,
        description="Outgoing relationships from this table to other tables",
    )
    incoming: list[IncomingRelationship] | None = Field(
        default=None,
        description="Incoming relationships from tables that reference this table",
    )
    summary: RelationshipSummary | None = Field(
        default=None, description="Summary statistics for all relationships"
    )


class OutputConfig(BaseModel):
    """Output file configuration."""

    include_footer: bool = Field(
        default=False, description="Include row count footer in output files"
    )
    line_terminator: str | None = Field(
        default=None, description="Line terminator (e.g., 'CRLF')"
    )
    file_naming_example: str | None = Field(
        default=None, description="Example filename pattern"
    )


class UMFMetadata(BaseModel):
    """Additional UMF metadata."""

    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp"
    )
    created_by: str | None = Field(default=None, description="Creator identifier")
    pipeline_phase: int | None = Field(
        default=None,
        ge=1,
        le=7,
        description="Pipeline phase that created/updated this file",
    )
    source_file_modified: datetime | None = Field(
        default=None, description="Last modified timestamp of the source Excel file"
    )
    base_table_strategy: str | None = Field(
        default=None,
        description="Strategy for building base table. Use 'union_sources' to build "
        "from UNION of source_tables.",
    )
    base_table: str | None = Field(
        default=None,
        description="Explicit base table name for SQL generation. Overrides automatic "
        "base table inference.",
    )
    source_tables: list[str] | None = Field(
        default=None,
        description="Source table names for union_sources strategy.",
    )
    unpivot_columns: list[str] | None = Field(
        default=None,
        description="Source columns to UNPIVOT into rows.",
    )
    unpivot_value_column: str | None = Field(
        default=None,
        description="Output column name for the unpivoted values.",
    )
    dedup_strategy: Literal["latest"] | None = Field(
        default=None,
        description="Deduplication strategy for generated tables. "
        "'latest': deduplicate on primary_key, keeping the row with the most recent load date.",
    )
    output_config: OutputConfig | None = Field(
        default=None, description="Output file configuration"
    )


class IngestionExclusionRule(BaseModel):
    """Pre-upsert exclusion rule using cross-table data.

    Rows matching the exclusion are dropped before upsert, preserving
    existing ingested data for those keys.
    """

    cross_pipeline_table: str = Field(
        description="Cross-pipeline table reference: 'pipeline.table'"
    )
    join_column: str = Field(description="Column in this table to join on")
    cross_pipeline_join_column: str = Field(
        description="Column in the cross-pipeline table to join on"
    )
    exclude_when: str = Field(
        description="SQL expression evaluated on joined row. "
        "When true, the row is excluded from upsert. "
        "References this table's columns as 'src.*' and cross-pipeline columns as 'xref.*'."
    )
    description: str | None = Field(
        default=None, description="Human-readable description"
    )


class PostUpsertRule(BaseModel):
    """Post-upsert rule to update flags on ingested data.

    Supports optional cross-pipeline table references for conditions that need
    to check external data (e.g., mark as deleted if member disenrolled in another table).
    """

    flag_column: str = Field(description="Column to set (e.g., 'is_deleted')")
    flag_value: str = Field(description="Value to set (e.g., 'true')")
    condition: str = Field(
        description="SQL condition identifying rows to flag. "
        "Can reference table columns directly. "
        "Use '{this_table}' as placeholder for the current table name. "
        "If cross_pipeline_table is set, use '{xref}' to reference the cross-pipeline table."
    )
    description: str | None = Field(
        default=None, description="Human-readable description"
    )
    cross_pipeline_table: str | None = Field(
        default=None,
        description="Optional cross-pipeline table ref: 'pipeline.table' for conditions "
        "that need external data. When set, the table is registered as '{xref}' temp view.",
    )
    join_column: str | None = Field(
        default=None,
        description="Column in this table to join on (required if cross_pipeline_table is set)",
    )
    cross_pipeline_join_column: str | None = Field(
        default=None,
        description="Column in the cross-pipeline table to join on "
        "(required if cross_pipeline_table is set)",
    )


class IngestionConfig(BaseModel):
    """Configuration for ingestion behavior.

    Controls how data from multiple files is deduplicated and written.
    """

    mode: Literal["snapshot", "incremental"] = Field(
        default="incremental",
        description="'snapshot': Filter to latest file, overwrite table. "
        "'incremental': Keep latest per PK, upsert to table.",
    )
    order_by: list[str] | None = Field(
        default=None,
        description="Columns to determine 'latest' (sorted descending). Can include: "
        "filename-extracted columns (e.g., 'file_date_yyyymmdd') or "
        "metadata columns (e.g., 'meta_source_name', 'meta_snapshot_dt', 'meta_load_dt'). "
        "For snapshot mode: filters to rows with MAX values of these columns. "
        "For incremental mode: orders rows when deduping by primary key.",
    )
    pre_upsert_exclusions: list[IngestionExclusionRule] | None = Field(
        default=None,
        description="Cross-pipeline exclusion rules applied before upsert. "
        "Matching rows are dropped, preserving existing ingested data for those keys.",
    )
    post_upsert_rules: list[PostUpsertRule] | None = Field(
        default=None,
        description="Rules applied after upsert to set flags (e.g., soft-delete) on ingested data.",
    )


# =============================================================================
# Unified Expectation Suite (ADR-005)
# =============================================================================


class ExpectationMeta(BaseModel):
    """Structured metadata for a single expectation."""

    stage: Literal["raw", "ingested", "unknown"] = "unknown"
    severity: Literal["critical", "error", "warning", "info"] = "warning"
    blocking: bool = False
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    generated_from: str | None = None  # "baseline", "profiling", "llm", "user"

    def to_gx_meta(self) -> dict[str, Any]:
        """Serialize to GX-compatible meta dict."""
        meta: dict[str, Any] = {}
        if self.stage != "unknown":
            meta["validation_stage"] = self.stage
        meta["severity"] = self.severity
        if self.blocking:
            meta["blocking"] = True
        if self.description:
            meta["description"] = self.description
        if self.tags:
            meta["tags"] = self.tags
        if self.generated_from:
            meta["generated_from"] = self.generated_from
        return meta

    @classmethod
    def from_gx_meta(
        cls, meta: dict[str, Any], expectation_type: str | None = None
    ) -> "ExpectationMeta":
        """Parse from GX meta dict. Auto-classifies stage from expectation_type if not in meta."""
        stage = meta.get("validation_stage", "unknown")
        if stage == "unknown" and expectation_type:
            stage = classify_validation_type(expectation_type)
        return cls(
            stage=stage,
            severity=meta.get("severity", "warning"),
            blocking=meta.get("blocking", False),
            description=meta.get("description"),
            tags=meta.get("tags", []),
            generated_from=meta.get("generated_from"),
        )


class Expectation(BaseModel):
    """A single validation expectation with structured metadata."""

    type: str
    kwargs: dict[str, Any] = Field(default_factory=dict)
    meta: ExpectationMeta = Field(default_factory=ExpectationMeta)

    def to_gx_dict(self) -> dict[str, Any]:
        """Convert to GX expectation dict format."""
        return {
            "type": self.type,
            "kwargs": self.kwargs,
            "meta": self.meta.to_gx_meta(),
        }

    @classmethod
    def from_gx_dict(cls, d: dict[str, Any]) -> "Expectation":
        """Parse from GX expectation dict."""
        exp_type = d.get("type", d.get("expectation_type", ""))
        raw_meta = d.get("meta", {})
        return cls(
            type=exp_type,
            kwargs=d.get("kwargs", {}),
            meta=ExpectationMeta.from_gx_meta(raw_meta, expectation_type=exp_type),
        )


class ExpectationSuite(BaseModel):
    """Unified collection of all expectations for a table, classified by stage."""

    expectations: list[Expectation] = Field(default_factory=list)
    thresholds: dict[str, Any] | None = None
    alert_config: dict[str, Any] | None = None
    pending: list[Expectation] = Field(default_factory=list)

    @property
    def raw(self) -> list[Expectation]:
        """Expectations for Bronze.Raw stage."""
        return [e for e in self.expectations if e.meta.stage == "raw"]

    @property
    def ingested(self) -> list[Expectation]:
        """Expectations for Bronze.Ingested stage."""
        return [e for e in self.expectations if e.meta.stage == "ingested"]

    @property
    def unclassified(self) -> list[Expectation]:
        """Expectations with unknown stage."""
        return [e for e in self.expectations if e.meta.stage == "unknown"]


class UMF(BaseModel):
    """Universal Metadata Format model."""

    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+$")] = Field(
        description="UMF format version"
    )
    table_name: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=128)
    ] = Field(description="Database table name")
    canonical_name: str | None = Field(
        default=None,
        description="Canonical name from source specifications (original case, any format). "
        "Can contain spaces, special characters, etc. Exact match to Excel tab name or specification.",
    )
    aliases: list[str] | None = Field(
        default=None,
        description="Alternative names for this table (e.g., sheet name variations, case variants). "
        "Used for resolving references when table names don't match exactly.",
    )
    source_sheet_name: str | None = Field(
        default=None,
        description="Original Excel sheet name from source specification. "
        "Stored for provenance tracking when canonical_name is derived from filename patterns.",
    )
    source_file: str | None = Field(
        default=None, description="Original source file name"
    )
    sheet_name: str | None = Field(
        default=None, description="Excel sheet name if applicable"
    )
    description: str | None = Field(
        default=None, description="Human-readable table description"
    )
    table_type: str | None = Field(
        default=None,
        description="Table classification: data_table, lookup_table, or configuration",
    )
    columns: list[UMFColumn] = Field(
        min_length=1, description="Array of column definitions"
    )
    primary_key: list[str] | None = Field(
        default=None,
        description="Primary key column names (single or compound).",
    )
    unique_constraints: list[list[str]] | None = Field(
        default=None,
        description="Unique constraint column combinations (non-primary compound uniqueness). "
        "Each inner list represents a set of columns that must be unique together.",
    )
    file_format: FileFormatSpec | None = Field(
        default=None,
        description="File format specification for ingestion (delimiter, encoding, etc.)",
    )
    source: SourceSpec | None = Field(
        default=None,
        description="Source shape declaration (ADR-015), discriminated on 'kind' "
        "(delimited | parquet | jdbc). When absent the table is a delimited "
        "flat file described by file_format (or its defaults); resolve via "
        "effective_source().",
    )
    validation_rules: ValidationRules | None = Field(
        default=None, description="Validation rules added by Phase 4"
    )
    quality_checks: QualityChecks | None = Field(
        default=None,
        description="Post-ingestion data quality checks for fitness assessment",
    )
    expectations: ExpectationSuite | None = Field(
        default=None,
        description="Unified expectation suite (replaces validation_rules + quality_checks)",
    )
    relationships: Relationships | None = Field(
        default=None, description="Table relationships added by Phase 4"
    )
    metadata: UMFMetadata | None = Field(
        default=None, description="Additional metadata"
    )
    config_data: dict[str, Any] | None = Field(
        default=None, description="Configuration data for configuration-type tables"
    )
    lookup_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Lookup table metadata including sample data and structure",
    )
    sample_data_cases: list[dict[str, Any]] | None = Field(
        default=None,
        description="Forced test cases for sample data generation. Each dict defines column values "
        "that must be included in generated sample data to test specific scenarios "
        "(e.g., edge cases, cross-table relationships).",
    )
    derivations: dict[str, Any] | None = Field(
        default=None,
        description="Derivation metadata including LLM generation info, mappings, "
        "survivorship strategies, and normalization rules",
    )
    ingestion: IngestionConfig | None = Field(
        default=None,
        description="Ingestion strategy. Controls file filtering, deduplication, and write mode.",
    )
    context_column: str | None = Field(
        default=None,
        description="Column used for context-based conditional validation (e.g. 'LOB' for "
        "healthcare line-of-business, 'segment' for fintech). When set, nullable rules with "
        "per-context keys generate filtered expectations using row_condition.",
    )

    def effective_source(self) -> "DelimitedSource | ParquetSource | JdbcSource":
        """Resolve the effective source shape for this table (ADR-015).

        Returns ``source`` when declared; otherwise derives a
        :class:`DelimitedSource` from ``file_format`` (or pure defaults when
        neither is declared). Never mutates the model -- a legacy UMF that
        declares only ``file_format`` (or nothing) must round-trip
        byte-identically through load -> save.
        """
        if self.source is not None:
            return self.source
        if self.file_format is not None:
            return DelimitedSource(**self.file_format.model_dump())
        return DelimitedSource()

    @field_validator("columns")
    @classmethod
    def unique_column_names(cls, v) -> list[UMFColumn]:
        """Validate that column names are unique."""
        names = [col.name for col in v]
        if len(names) != len(set(names)):
            msg = "Column names must be unique"
            raise ValueError(msg)
        return v

    @field_validator("primary_key")
    @classmethod
    def validate_primary_key_columns(cls, v, info) -> list[str] | None:
        """Validate that primary key columns exist in the columns list.

        Note: meta_* columns (added during ingestion) are skipped
        since they don't exist in the UMF columns list.
        """
        if v is None:
            return v

        # Get column names from columns field
        columns_data = info.data.get("columns", [])
        if not columns_data:
            return v

        # Build column lookup by name
        columns_by_name: dict[str, Any] = {}
        for col in columns_data:
            name = col["name"] if isinstance(col, dict) else col.name
            columns_by_name[name] = col

        # Check each primary key column
        for pk_col in v:
            if pk_col.startswith("meta_"):
                continue  # Skip provenance columns added during ingestion

            # Error: PK column doesn't exist
            if pk_col not in columns_by_name:
                msg = f"Primary key column '{pk_col}' not found in table columns"
                raise ValueError(msg)

        return v

    @model_validator(mode="after")
    def validate_context_column(self) -> Self:
        """Validate that context_column references an existing column."""
        if self.context_column is not None:
            col_names = {col.name for col in self.columns}
            if self.context_column not in col_names:
                msg = f"context_column '{self.context_column}' not found in columns: {sorted(col_names)}"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def warn_deprecated_legacy_fields(self) -> Self:
        """Emit DeprecationWarning when legacy expectation fields are populated.

        ADR-005 Phase C: consumers have migrated to ExpectationSuite.
        The validation_rules and quality_checks fields are retained for
        backward-compatible loading but should not be populated directly.
        """
        if self.validation_rules is not None:
            warnings.warn(
                "UMF.validation_rules is deprecated. Use UMF.expectations "
                "(ExpectationSuite) instead. See ADR-005.",
                DeprecationWarning,
                stacklevel=2,
            )
        if self.quality_checks is not None:
            warnings.warn(
                "UMF.quality_checks is deprecated. Use UMF.expectations "
                "(ExpectationSuite) instead. See ADR-005.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self

    @field_validator("version")
    @classmethod
    def validate_version_format(cls, v) -> str:
        """Validate version format is numeric."""
        parts = v.split(".")
        try:
            [int(part) for part in parts]
        except ValueError as e:
            msg = f"Invalid version format: {v}"
            raise ValueError(msg) from e
        return v

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "version": "1.0",
                "table_name": "Medical_Claims",
                "source_file": "Centene Outbound Outreach Data Layouts v2.5 2026.xlsx",
                "sheet_name": "Medical Claims",
                "description": "Healthcare claims and billing information",
                "columns": [
                    {
                        "name": "PBPTYPE",
                        "data_type": "VARCHAR",
                        "position": "A",
                        "description": "Line of Business",
                        "nullable": {"MD": False, "MP": False, "ME": False},
                        "sample_values": ["MEDICAID", "MEDICARE", "MARKETPLACE"],
                        "length": 20,
                    }
                ],
            }
        },
    )


def load_umf_from_yaml(yaml_path: str | Path) -> UMF:
    """Load and validate UMF from YAML file.

    Args:
        yaml_path: Path to UMF YAML file

    Returns:
        Validated UMF model

    Raises:
        ValidationError: If UMF data is invalid
        FileNotFoundError: If file doesn't exist

    """
    from pathlib import Path

    import yaml

    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        msg = f"UMF file not found: {yaml_file}"
        raise FileNotFoundError(msg)

    with yaml_file.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return UMF(**data)


def save_umf_to_yaml(umf: UMF, yaml_path: str | Path) -> None:
    """Save UMF model to YAML file.

    Args:
        umf: UMF model to save
        yaml_path: Output YAML file path

    """
    from pathlib import Path

    yaml_file = Path(yaml_path)
    yaml_file.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict and remove None values for cleaner output
    data = umf.model_dump(exclude_none=True)

    import yaml as yaml_lib

    with yaml_file.open("w", encoding="utf-8") as f:
        yaml_lib.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


# Re-export for convenience (valid names only)
__all__ = [
    "INGESTED_QUALITY_CHECK_TYPES",
    "RAW_VALIDATION_TYPES",
    "REDUNDANT_VALIDATION_TYPES",
    "TYPED_RAW_SOURCE_KINDS",
    "UMF",
    "Cardinality",
    "DelimitedSource",
    "DerivationCandidate",
    "FileFormat",
    "FileFormatSpec",
    "FilenamePattern",
    "ForeignKey",
    "IncomingRelationship",
    "Index",
    "IngestionConfig",
    "IngestionExclusionRule",
    "JdbcSource",
    "JoinViaSpec",
    "Nullable",
    "OutgoingRelationship",
    "OutputConfig",
    "ParquetSource",
    "PostUpsertRule",
    "QualityCheck",
    "QualityChecks",
    "ReferencedBy",
    "RelationshipSummary",
    "Relationships",
    "SourceSpec",
    "Survivorship",
    "UMFColumn",
    "UMFColumnDerivation",
    "UMFMetadata",
    "ValidationRule",
    "ValidationRules",
    "classify_validation_type",
    "load_umf_from_yaml",
    "save_umf_to_yaml",
]
