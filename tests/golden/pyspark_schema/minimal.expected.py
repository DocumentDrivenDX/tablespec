# SPDX-License-Identifier: MIT OR Apache-2.0
# PySpark Schema for users
# Generated from UMF specification
# Source file modified: 2025-01-15 10:30:00
# NOTE: Includes data + filename-sourced columns; excludes meta_* provenance columns

from pyspark.sql.types import StructType, StructField
from pyspark.sql.types import StringType, IntegerType, LongType, DecimalType
from pyspark.sql.types import FloatType, DoubleType, BooleanType, DateType, TimestampType

users_schema = StructType([
    StructField("id", IntegerType(), False),
    StructField("name", StringType(), False),
    StructField("email", StringType(), True)
])
