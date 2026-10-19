# SPDX-License-Identifier: MIT OR Apache-2.0
# PySpark Schema for AllTypesDemo
# Generated from UMF specification
# Source file modified: 2025-01-15 10:30:00
# NOTE: Includes data + filename-sourced columns; excludes meta_* provenance columns

from pyspark.sql.types import StructType, StructField
from pyspark.sql.types import StringType, IntegerType, LongType, DecimalType
from pyspark.sql.types import FloatType, DoubleType, BooleanType, DateType, TimestampType

all_types_demo_schema = StructType([
    StructField("col_varchar", StringType(), True),
    StructField("col_integer", IntegerType(), True),
    StructField("col_decimal", DecimalType(), True),
    StructField("col_float", FloatType(), True),
    StructField("col_boolean", BooleanType(), True),
    StructField("col_date", StringType(), True),
    StructField("col_datetime", TimestampType(), True),
    StructField("col_text", StringType(), True),
    StructField("col_char", StringType(), True)
])
