# JDBC onboarding (first-class source path)

JDBC is a first-class FEAT-031 source kind: the same UMF → compile → runtime
contract as delimited, with **typed raw** landing via Spark's JDBC connector
(tablespec never opens a DB connection itself).

## Composition

```python
from tablespec.profiling import JdbcToUmfMapper  # requires tablespec[spark]
from tablespec import bootstrap_from_specs  # or compile_umfs after discovery
from tablespec.ingestion import get_reader

# 1) Discover UMF from INFORMATION_SCHEMA (Spark JDBC)
mapper = JdbcToUmfMapper(spark, jdbc_url=..., options={...})
umfs = mapper.discover(["dbo.customers", "dbo.orders"])  # shape may vary by mapper API

# 2) Compile (no live DB required once UMF is in hand)
from tablespec.e2e.compile import compile_umfs
artifacts = compile_umfs(umfs, "/tmp/jdbc-out", source="tables", dialect="spark")

# 3) Runtime land: Spark JDBC reader from the committed source: block
reader = get_reader(umf.effective_source())
df = reader.read(umf.effective_source(), spark)
```

### Public Path B when specs are already authored

If UMFs already declare `source: {kind: jdbc, ...}`:

```python
from tablespec import bootstrap_from_specs

artifacts = bootstrap_from_specs(
    ["specs/customers", "specs/orders"],
    out_dir="/tmp/jdbc-compile",
    dialect="spark",
)
```

`password_secret_ref` (or env-style secret name) is required; plaintext
passwords are rejected by the model.

## Demo / acceptance

| Lane | What | Gate |
|------|------|------|
| Local | Docker SQL Server + Northwind fixture | `tests/integration/test_jdbc_discovery.py`, `test_northwind_e2e.py` (skip without Docker) |
| Workspace | `notebooks/northwind-demo/` | Product microsite: Getting Started → In a workspace |

## Backbone note

The e2e **backbone** file loader supports `delimited` / `parquet` / `json`
batch files for local multi-engine parity. JDBC tables are landed at runtime
with `JdbcReader` + Spark — not by reading a CSV batch. That is intentional:
JDBC onboarding is proven by discovery + compile + integration/Northwind, not
by the CSV-shaped backbone corpus.

## Secret safety

- Never put credentials in UMF or compiled artifacts.
- Use `password_secret_ref` naming a Databricks secret scope or env var.
- Discovery and readers fail closed when the secret is missing.
