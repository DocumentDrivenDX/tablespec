# Cast dialects

Public cast dialects accepted by compile, emit, and bootstrap:

| Dialect | Role |
|---------|------|
| `duckdb` | Local/dev SQL and dbt-duckdb |
| `spark` | Spark-family cast SQL |
| `databricks` | **Public** Databricks-facing spelling; normalizes to the Spark-family cast path (byte-identical SQL to `spark` for shared casts) |

```python
from tablespec.dialects import CAST_DIALECTS, normalize_cast_dialect

assert set(CAST_DIALECTS) == {"spark", "databricks", "duckdb"}
assert normalize_cast_dialect("databricks") == "spark"
```

CLI flags (`emit`, `bootstrap`) use the same choice list. Prefer
`dialect="databricks"` in Databricks examples; prefer `duckdb` for local Path B.
