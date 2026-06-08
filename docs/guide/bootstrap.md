# Bootstrap from Spark Tables

Use the public bootstrap facade when you already have an existing Spark table
and want the full compiled artifact tree in one call.

```python
from tablespec import bootstrap_from_tables

artifacts = bootstrap_from_tables(
    spark,
    ["member"],
    out_dir="/tmp/tablespec-bootstrap",
    profile=True,
    dialect="spark",
)

print(artifacts.manifest_path)
print(artifacts.table("member").suite_json)
```

What the facade does:

- reflects each table schema into UMF
- when `profile=True`, profiles the table data natively and turns the profile
  into GX validation expectations
- compiles and persists the UMF snapshot, validation suite, dbt projects, LDP
  project, and manifest

The profiler enriches validation. It does not create UMF. Schema reflection does
that first step, and the facade handles the compile step for you.

When you only want the schema-only baseline suite, pass `profile=False`.
