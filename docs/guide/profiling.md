# Profiling Integration

tablespec profiles Spark DataFrames natively and turns the profile into Great
Expectations expectations.

For Databricks / Spark-table bootstrap, use the one-shot facade in
[Bootstrap from Spark Tables](bootstrap.md). That facade reflects schema into
UMF, optionally profiles the data, and compiles the full artifact tree. The
profiler enriches validation; it does not create UMF.

## Native Spark Profiling

```python
from tablespec import NativeSparkProfiler, ProfileToGxMapper

profiler = NativeSparkProfiler(spark)
profile = profiler.profile(spark_df)

gx_mapper = ProfileToGxMapper(strictness="medium")
expectations = gx_mapper.build_expectations(profile)
```

`profile` carries completeness, cardinality, numeric stats, quantiles, string
stats, and detected patterns. `ProfileToGxMapper` turns that profile into the
validation expectations that the bootstrap facade persists when `profile=True`.
