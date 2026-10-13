"""Output formatting utilities for applying UMF format specifications during export.

This module provides utilities to format DataFrame columns based on UMF format specifications
before writing to external formats (CSV, pipe-delimited, etc.). This is the complement to
casting_utils.py which handles INPUT formatting during ingestion.

Key difference from casting_utils:
- casting_utils: STRING → typed columns (to_date, to_timestamp)
- output_formatting: typed columns → formatted STRING (date_format)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tablespec.casting_utils import convert_umf_format_to_spark

if TYPE_CHECKING:
    from pyspark.sql import DataFrame

    from tablespec.models.umf import UMF

try:
    from pyspark.sql import functions as F

    _spark_available = True
except ImportError:
    _spark_available = False

SPARK_AVAILABLE = _spark_available

logger = logging.getLogger(__name__)


def apply_output_formats(df: DataFrame, umf: UMF) -> DataFrame:
    """Apply UMF format specifications to DataFrame columns for output.

    This function formats typed columns (DATE, TIMESTAMP, etc.) as strings according to
    their UMF format specifications. It's intended for use before writing data to external
    formats where string representation matters (CSV, pipe-delimited, etc.).

    Args:
    ----
        df: Spark DataFrame with typed columns
        umf: UMF specification containing format definitions

    Returns:
    -------
        DataFrame with formatted columns as strings where format is specified

    Examples:
    --------
        >>> # Format dates according to UMF specs
        >>> df_formatted = apply_output_formats(df, umf)
        >>> # If UMF has column with data_type=DATE, format="MM/DD/YYYY"
        >>> # The DATE column will be converted to string like "10/06/2025"

    Notes:
    -----
        - Only formats columns that have a `format` field defined in UMF
        - Uses Spark's date_format() for DATE and TIMESTAMP columns
        - Preserves original column names and order
        - Other columns pass through unchanged

    Raises:
    ------
        ImportError: If PySpark is not available

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for output formatting operations"
        raise ImportError(msg)

    # Build a mapping of column names to format specifications
    format_map: dict[str, tuple[str, str]] = {}  # column_name -> (data_type, format)

    for col in umf.columns:
        if col.format is not None:
            format_map[col.name] = (col.data_type, col.format)

    if not format_map:
        logger.debug("No columns with format specifications found in UMF")
        return df

    # Apply formatting to columns that exist in the DataFrame
    df_result = df
    formatted_count = 0

    for col_name, (data_type, umf_format) in format_map.items():
        # Check if column exists in DataFrame
        if col_name not in df.columns:
            logger.debug(f"Column {col_name} not found in DataFrame, skipping format")
            continue

        # Convert UMF format to Spark SimpleDateFormat pattern
        spark_format = convert_umf_format_to_spark(umf_format)

        # Apply formatting based on data type
        # Handle both PySpark type names (DateType, TimestampType) and SQL names (DATE, TIMESTAMP)
        data_type_upper = data_type.upper()
        # Strip "TYPE" suffix if present (DateType -> DATE, TimestampType -> TIMESTAMP)
        data_type_base = data_type_upper.removesuffix("TYPE")

        if data_type_base in ("DATE", "TIMESTAMP"):
            # Use date_format() to convert DATE/TIMESTAMP to formatted string
            logger.debug(
                f"Formatting column {col_name} ({data_type}) with format: "
                + f"{umf_format} -> {spark_format}"
            )
            df_result = df_result.withColumn(
                col_name, F.date_format(F.col(col_name), spark_format)
            )  # type: ignore[possibly-unbound]
            formatted_count += 1
        else:
            # For other types, format field might contain patterns not applicable
            # to Spark formatting functions (e.g., value enumerations, examples)
            logger.debug(
                f"Column {col_name} has format='{umf_format}' but data_type={data_type} "
                + "does not support output formatting - skipping"
            )

    logger.info(f"Applied output formatting to {formatted_count} column(s)")
    return df_result


def apply_null_replacements(df: DataFrame, umf: UMF) -> DataFrame:
    """Replace NULL values with configured output values.

    This function replaces NULL values in DataFrame columns with configured string values
    according to the UMF null_output_value field. This is used for output files where specific
    NULL representations are required (e.g., 'NA', 'N/A', 'NULL').

    Args:
    ----
        df: Spark DataFrame with columns to process
        umf: UMF specification containing null_output_value config

    Returns:
    -------
        DataFrame with NULL values replaced according to UMF config

    Examples:
    --------
        >>> # Replace NULLs with "NA" for specific columns
        >>> df_with_na = apply_null_replacements(df, umf)
        >>> # If UMF has column with null_output_value="NA"
        >>> # NULL values in that column become "NA" strings

    Notes:
    -----
        - Only affects columns with null_output_value configured in UMF
        - Columns without null_output_value preserve NULL values
        - Should be called AFTER apply_output_formats() in the processing pipeline
        - Works on any column type after type conversion to string

    Raises:
    ------
        ImportError: If PySpark is not available

    """
    if not SPARK_AVAILABLE:
        msg = "PySpark is required for NULL replacement operations"
        raise ImportError(msg)

    # Build mapping of columns with null_output_value configured
    null_value_map: dict[str, str] = {}
    for col in umf.columns:
        if col.null_output_value is not None:
            null_value_map[col.name] = col.null_output_value

    if not null_value_map:
        logger.debug("No columns with null_output_value configured")
        return df

    df_result = df
    replacement_count = 0

    for col_name, null_value in null_value_map.items():
        if col_name not in df.columns:
            logger.debug(
                f"Column {col_name} not found in DataFrame, skipping NULL replacement"
            )
            continue

        logger.debug(f"Replacing NULL values in column {col_name} with '{null_value}'")
        df_result = df_result.withColumn(
            col_name,
            F.when(F.col(col_name).isNull(), F.lit(null_value)).otherwise(
                F.col(col_name)
            ),  # type: ignore[possibly-unbound]
        )
        replacement_count += 1

    logger.info(f"Applied NULL replacements to {replacement_count} column(s)")
    return df_result
