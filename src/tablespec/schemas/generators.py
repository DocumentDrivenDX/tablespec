"""Schema Generators - SQL DDL, PySpark, and JSON Schema generation."""

from datetime import UTC, datetime
from typing import Any, TypedDict

from tablespec.type_mappings import map_to_json_type, map_to_pyspark_type


class JSONSchemaProperty(TypedDict, total=False):
    """JSON Schema property definition."""

    type: str
    description: str
    maxLength: int
    items: dict[str, Any]
    minItems: int
    maxItems: int
    examples: list[Any]


class JSONSchema(TypedDict, total=False):
    """JSON Schema structure."""

    properties: dict[str, JSONSchemaProperty]
    required: list[str]


def _resolve_nullable(nullable_value: Any) -> bool:
    """Resolve nullable value from bool, dict (context-specific), or None.

    Handles both simple boolean nullable flags and context-specific nullable dicts
    (e.g., {"MD": True, "MP": False, "ME": True} or any arbitrary context keys).

    Returns True (nullable) by default when value is missing or unrecognized.
    """
    if nullable_value is None:
        return True
    if isinstance(nullable_value, bool):
        return nullable_value
    if isinstance(nullable_value, dict):
        # If all LOBs allow null, column is nullable
        return all(nullable_value.values()) if nullable_value else True
    return True


def generate_sql_ddl(umf_data: dict[str, Any]) -> str:
    """Generate SQL DDL from UMF data."""
    table_name = umf_data["table_name"]
    canonical_name = umf_data.get("canonical_name") or table_name

    # Use source file modified time if available. Otherwise omit the timestamp
    # line so repeated renders of the same spec stay byte-identical.
    metadata = umf_data.get("metadata") or {}
    source_modified = metadata.get("source_file_modified") if metadata else None

    ddl_lines = [
        f"-- DDL for {canonical_name}",
        "-- Generated from UMF specification",
        "",
        f"CREATE TABLE {table_name} (",
    ]
    if source_modified:
        # Parse and format the ISO timestamp
        timestamp = datetime.fromisoformat(source_modified).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        ddl_lines.insert(2, f"-- Source file modified: {timestamp}")

    columns = []
    for col in umf_data["columns"]:
        col_name = col["name"]
        data_type = col.get("data_type", "VARCHAR")
        is_nullable = _resolve_nullable(col.get("nullable"))
        nullable = "" if is_nullable else " NOT NULL"

        # Handle specific data types
        if data_type == "VARCHAR" and col.get("max_length"):
            data_type = f"VARCHAR({col['max_length']})"
        elif data_type == "VARCHAR":
            # Spark SQL requires size for VARCHAR; use STRING when unspecified
            data_type = "STRING"
        elif data_type == "DECIMAL" and col.get("precision"):
            precision = col["precision"]
            scale = col.get("scale", 0)
            data_type = f"DECIMAL({precision},{scale})"
        elif data_type.upper().startswith("EMBEDDING"):
            data_type = "ARRAY<FLOAT>"

        col_def = f"    {col_name} {data_type}{nullable}"

        # Add comment if description available
        if col.get("description"):
            escaped_desc = col["description"].replace("'", "''")[:255]
            col_def += f" COMMENT '{escaped_desc}'"

        columns.append(col_def)

    ddl_lines.append(",\n".join(columns))
    ddl_lines.append(")")

    # Add table comment
    if umf_data.get("description"):
        escaped_table_desc = umf_data["description"].replace("'", "''")[:255]
        ddl_lines.append(f"COMMENT '{escaped_table_desc}'")

    ddl_lines.append(";")

    # Add indexes if available
    relationships = umf_data.get("relationships") or {}
    if relationships.get("suggested_indexes"):
        ddl_lines.append("")
        ddl_lines.append("-- Suggested Indexes")

        for idx in umf_data["relationships"]["suggested_indexes"]:
            idx_name = idx["name"]
            idx_columns = ", ".join(idx["columns"])
            ddl_lines.append(
                f"CREATE INDEX {idx_name} ON {table_name} ({idx_columns});"
            )

    return "\n".join(ddl_lines)


def generate_pyspark_schema(umf_data: dict[str, Any]) -> str:
    """Generate PySpark schema from UMF data.

    Includes:
        - Data columns from source files
        - Filename-sourced business columns (extracted during ingestion)

    Excludes:
        - Provenance metadata columns (meta_*) - added at runtime, standardized across all tables
    """
    table_name = umf_data["table_name"]
    canonical_name = umf_data.get("canonical_name") or table_name

    # Use source file modified time if available, otherwise use current time
    metadata = umf_data.get("metadata") or {}
    source_modified = metadata.get("source_file_modified") if metadata else None
    if source_modified:
        # Parse and format the ISO timestamp
        from datetime import datetime as dt

        timestamp = dt.fromisoformat(source_modified).strftime("%Y-%m-%d %H:%M:%S")
    else:
        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    needs_array_type = any(
        (col.get("data_type", "").upper().startswith("EMBEDDING"))
        for col in umf_data["columns"]
    )

    type_imports = "from pyspark.sql.types import FloatType, DoubleType, BooleanType, DateType, TimestampType"
    if needs_array_type:
        type_imports += ", ArrayType"

    schema_lines = [
        f"# PySpark Schema for {canonical_name}",
        "# Generated from UMF specification",
        f"# Source file modified: {timestamp}",
        "# NOTE: Includes data + filename-sourced columns; excludes meta_* provenance columns",
        "",
        "from pyspark.sql.types import StructType, StructField",
        "from pyspark.sql.types import StringType, IntegerType, LongType, DecimalType",
        type_imports,
        "",
        f"{table_name.lower()}_schema = StructType([",
    ]

    fields = []
    for col in umf_data["columns"]:
        col_name = col["name"]
        data_type = col.get("data_type", "VARCHAR")
        nullable = _resolve_nullable(col.get("nullable"))

        # Map data types to PySpark types
        pyspark_type = map_to_pyspark_type(data_type)

        field_def = f'    StructField("{col_name}", {pyspark_type}, {nullable})'
        fields.append(field_def)

    schema_lines.append(",\n".join(fields))
    schema_lines.append("])")

    return "\n".join(schema_lines)


def generate_json_schema(umf_data: dict[str, Any]) -> dict[str, Any]:
    """Generate JSON schema from UMF data."""
    table_name = umf_data["table_name"]
    canonical_name = umf_data.get("canonical_name") or table_name

    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{canonical_name} Schema",
        "type": "object",
        "description": umf_data.get("description", f"Schema for {canonical_name} table"),
        "properties": {},
        "required": [],
    }

    for col in umf_data["columns"]:
        col_name = col["name"]
        col_desc = col.get("description", "")
        nullable = _resolve_nullable(col.get("nullable"))

        # Map data type to JSON schema type
        json_type = map_to_json_type(col.get("data_type", "VARCHAR"))

        prop: JSONSchemaProperty = {"type": json_type, "description": col_desc}

        # Add additional constraints
        if col.get("max_length"):
            prop["maxLength"] = col["max_length"]

        if col.get("data_type", "").upper().startswith("EMBEDDING") and col.get("dimension"):
            prop["items"] = {"type": "number"}
            prop["minItems"] = col["dimension"]
            prop["maxItems"] = col["dimension"]

        if col.get("sample_values"):
            prop["examples"] = col["sample_values"][:3]

        schema["properties"][col_name] = prop

        # Add to required if not nullable
        if not nullable:
            schema["required"].append(col_name)

    return schema
