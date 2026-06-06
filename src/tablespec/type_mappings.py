"""Type mapping utilities for converting between different type systems."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql.types import DataType

# Valid PySpark type names for UMF column data_type and expectation type_ parameters
VALID_PYSPARK_TYPES = frozenset(
    {
        "StringType",
        "IntegerType",
        "LongType",
        "ShortType",
        "ByteType",
        "DecimalType",
        "FloatType",
        "DoubleType",
        "BooleanType",
        "DateType",
        "TimestampType",
    }
)

# PySpark + SQL type names denoting a NUMERIC column. Numeric value-constraints
# (ranges, value-sets) must compare as NUMBERS, so they validate on the TYPED
# (ingested) stage -- on the raw all-string stage 1.5 never equals "1.50".
NUMERIC_TYPE_NAMES = frozenset(
    {
        "IntegerType",
        "LongType",
        "ShortType",
        "ByteType",
        "DecimalType",
        "FloatType",
        "DoubleType",
        "INTEGER",
        "INT",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "DECIMAL",
        "NUMERIC",
        "FLOAT",
        "DOUBLE",
        "REAL",
    }
)


def is_numeric_data_type(data_type: str | None) -> bool:
    """Whether a UMF/PySpark ``data_type`` name denotes a numeric column.

    Accepts PySpark names (``"DoubleType"``) and SQL names (``"DECIMAL"``), with
    or without precision/parens (``"DECIMAL(10,2)"``, ``"DecimalType()"``).
    """
    if not data_type:
        return False
    base = data_type.split("(")[0].strip().rstrip("()")
    return base in NUMERIC_TYPE_NAMES or base.upper() in NUMERIC_TYPE_NAMES


def map_pyspark_to_sql_type(data_type: str) -> str:
    """Map PySpark type names to SQL type names for casting.

    Converts PySpark type names (e.g., "StringType", "DateType") to SQL type names
    (e.g., "STRING", "DATE") for use with Spark SQL casting functions.

    Args:
    ----
        data_type: PySpark type name (e.g., "StringType", "DateType", "IntegerType")
                   or SQL type name (returned as-is)

    Returns:
    -------
        SQL type name (e.g., "STRING", "DATE", "INTEGER")

    """
    # PySpark to SQL mapping
    pyspark_to_sql = {
        "StringType": "STRING",
        "IntegerType": "INTEGER",
        "LongType": "BIGINT",
        "ShortType": "SMALLINT",
        "ByteType": "TINYINT",
        "DecimalType": "DECIMAL",
        "FloatType": "FLOAT",
        "DoubleType": "DOUBLE",
        "BooleanType": "BOOLEAN",
        "DateType": "DATE",
        "TimestampType": "TIMESTAMP",
    }

    # Remove parentheses if present (e.g., "StringType()" -> "StringType")
    base_type = data_type.rstrip("()")

    # If it's a PySpark type, convert to SQL
    if base_type in pyspark_to_sql:
        return pyspark_to_sql[base_type]

    # If it looks like a SQL type (uppercase), return as-is
    if data_type.isupper():
        return data_type

    # Default to STRING
    return "STRING"


def map_to_gx_spark_type(data_type: str) -> str:
    """Map UMF data type to Great Expectations Spark type name.

    These are the PySpark type names that Great Expectations expects when validating
    Spark DataFrames using expect_column_values_to_be_of_type.

    Args:
    ----
        data_type: UMF data type - SQL style (e.g., "VARCHAR", "INTEGER", "DATE")
                   or PySpark style (e.g., "StringType", "IntegerType") for backward
                   compatibility

    Returns:
    -------
        PySpark type name (e.g., "StringType", "IntegerType", "TimestampType")

    """
    # SQL-style UMF type mapping (preserves DATE -> StringType per ADR-001)
    mapping = {
        "VARCHAR": "StringType",
        "STRING": "StringType",
        "INTEGER": "IntegerType",
        "INT": "IntegerType",
        "BIGINT": "LongType",
        "SMALLINT": "ShortType",
        "TINYINT": "ByteType",
        "DECIMAL": "DecimalType",
        "FLOAT": "FloatType",
        "DOUBLE": "DoubleType",
        "BOOLEAN": "BooleanType",
        "DATE": "StringType",  # Dates stored as YYYYMMDD strings (ADR-001)
        "DATETIME": "TimestampType",
        "TIMESTAMP": "TimestampType",
    }

    # If already a valid PySpark type name, return as-is
    if data_type in VALID_PYSPARK_TYPES:
        return data_type

    # Remove parentheses if present (e.g., "StringType()" -> "StringType")
    base_type = data_type.rstrip("()")
    if base_type in VALID_PYSPARK_TYPES:
        return base_type

    # Otherwise try SQL-style mapping
    return mapping.get(data_type.upper(), "StringType")


def map_to_pyspark_type(data_type: str) -> str:
    """Map UMF data type to PySpark type with instantiation.

    Returns type with parentheses for use in StructField definitions.

    Args:
    ----
        data_type: UMF data type - SQL style (e.g., "VARCHAR", "INTEGER", "DATE")
                   or PySpark style (e.g., "StringType", "IntegerType") for backward
                   compatibility

    Returns:
    -------
        PySpark type with instantiation (e.g., "StringType()", "IntegerType()")

    """
    # SQL-style UMF type mapping (preserves DATE -> StringType per ADR-001)
    mapping = {
        "VARCHAR": "StringType()",
        "STRING": "StringType()",
        "INTEGER": "IntegerType()",
        "INT": "IntegerType()",
        "BIGINT": "LongType()",
        "SMALLINT": "ShortType()",
        "TINYINT": "ByteType()",
        "DECIMAL": "DecimalType()",
        "FLOAT": "FloatType()",
        "DOUBLE": "DoubleType()",
        "BOOLEAN": "BooleanType()",
        "DATE": "StringType()",  # Dates stored as YYYYMMDD strings (ADR-001)
        "DATETIME": "TimestampType()",
        "TIMESTAMP": "TimestampType()",
    }

    # If already a PySpark type name (with or without parentheses), normalize it
    if data_type in VALID_PYSPARK_TYPES:
        return f"{data_type}()"

    # Remove parentheses if present and check again
    base_type = data_type.rstrip("()")
    if base_type in VALID_PYSPARK_TYPES:
        return f"{base_type}()"

    # Otherwise try SQL-style mapping
    return mapping.get(data_type.upper(), "StringType()")


def map_to_json_type(data_type: str) -> str:
    """Map UMF data type to JSON schema type.

    Args:
    ----
        data_type: UMF data type (e.g., "VARCHAR", "INTEGER", "DATE")

    Returns:
    -------
        JSON schema type (e.g., "string", "integer", "number")

    """
    mapping = {
        "VARCHAR": "string",
        "STRING": "string",
        "INTEGER": "integer",
        "INT": "integer",
        "BIGINT": "integer",
        "DECIMAL": "number",
        "FLOAT": "number",
        "DOUBLE": "number",
        "BOOLEAN": "boolean",
        "DATE": "string",
        "DATETIME": "string",
        "TIMESTAMP": "string",
    }
    return mapping.get(data_type.upper(), "string")


def map_to_pyspark_type_obj(data_type: str) -> "DataType":
    """Map UMF data type to actual PySpark DataType object.

    Unlike map_to_pyspark_type() which returns strings, this returns
    actual PySpark type instances for use in StructField construction.

    Requires PySpark to be installed (available with tablespec[spark]).

    Args:
    ----
        data_type: UMF data type - PySpark style (e.g., "StringType", "DateType")
                   or SQL style (e.g., "STRING", "DATE")

    Returns:
    -------
        PySpark DataType instance (e.g., StringType(), DateType())

    Raises:
    ------
        ImportError: If PySpark is not installed.

    """
    from pyspark.sql.types import (
        BooleanType,
        ByteType,
        DateType,
        DecimalType,
        DoubleType,
        FloatType,
        IntegerType,
        LongType,
        ShortType,
        StringType,
        TimestampType,
    )

    # Normalize to base type name (uppercase, no parentheses)
    base_type = data_type.rstrip("()").upper()

    type_map: dict[str, DataType] = {
        "STRING": StringType(),
        "STRINGTYPE": StringType(),
        "VARCHAR": StringType(),
        "INTEGER": IntegerType(),
        "INTEGERTYPE": IntegerType(),
        "INT": IntegerType(),
        "LONG": LongType(),
        "LONGTYPE": LongType(),
        "BIGINT": LongType(),
        "SHORT": ShortType(),
        "SHORTTYPE": ShortType(),
        "SMALLINT": ShortType(),
        "BYTE": ByteType(),
        "BYTETYPE": ByteType(),
        "TINYINT": ByteType(),
        "DECIMAL": DecimalType(),
        "DECIMALTYPE": DecimalType(),
        "FLOAT": FloatType(),
        "FLOATTYPE": FloatType(),
        "DOUBLE": DoubleType(),
        "DOUBLETYPE": DoubleType(),
        "BOOLEAN": BooleanType(),
        "BOOLEANTYPE": BooleanType(),
        "DATE": DateType(),
        "DATETYPE": DateType(),
        "DATETIME": TimestampType(),
        "TIMESTAMP": TimestampType(),
        "TIMESTAMPTYPE": TimestampType(),
    }

    return type_map.get(base_type, StringType())
