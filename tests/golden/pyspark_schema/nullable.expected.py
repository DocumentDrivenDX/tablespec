# SPDX-License-Identifier: MIT OR Apache-2.0
# PySpark Schema for claims
# Generated from UMF specification
# Source file modified: 2025-01-15 10:30:00
# NOTE: Includes data + filename-sourced columns; excludes meta_* provenance columns

from pyspark.sql.types import StructType, StructField
from pyspark.sql.types import StringType, IntegerType, LongType, DecimalType
from pyspark.sql.types import FloatType, DoubleType, BooleanType, DateType, TimestampType

claims_schema = StructType([
    StructField("claim_id", StringType(), False),
    StructField("member_id", StringType(), False),
    StructField("diagnosis_code", StringType(), True),
    StructField("amount", DecimalType(), False),
    StructField("notes", StringType(), True)
])
