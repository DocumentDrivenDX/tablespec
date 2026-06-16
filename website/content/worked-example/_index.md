---
title: Worked Example
description: "A complete tablespec walkthrough from split-format UMF to SQL, dbt, Lakeflow, and Great Expectations artifacts."
weight: 2
next: /concepts
---

This example is for readers who want to see one source table move through
tablespec from metadata to generated files. It starts with a Universal
Metadata Format (UMF) spec for `medical_claims` and ends with SQL, dbt, JSON
Schema, and Great Expectations artifacts a data team can review and run.

## Scenario

A claims feed arrives with source column names and business-specific
nullability. In this example, ingested bronze means the source table has a
reviewed contract and generated runtime artifacts. The goal is not to rename,
enrich, dedupe, or resolve entities. Those are silver-layer decisions. The
goal is to finish ingested bronze:

- source fields are captured with their source names
- source types and nullability are declared
- keys and relationships are explicit
- validation criteria are generated
- runtime artifacts are committed for review

## 1. Author the table contract

A split-format UMF stores table metadata in `table.yaml` and one column file
per source field under `columns/`. That layout keeps changes reviewable. The
table file names the source table and its key:

```yaml
# tables/medical_claims/table.yaml
table_name: medical_claims
canonical_name: Medical Claims
description: Medical claims - source-semantic ingested bronze
version: '1.0'
primary_key:
  - claim_id
```

Column files preserve source field names and source nullability:

```yaml
# tables/medical_claims/columns/claim_id.yaml
column:
  name: claim_id
  data_type: VARCHAR
  length: 50
  description: Source claim identifier
  nullable:
    MD: false
    MP: false
```

```yaml
# tables/medical_claims/columns/service_date.yaml
column:
  name: service_date
  data_type: DATE
  description: Date of service from the source feed
  nullable:
    MD: false
    MP: true
```

## 2. Validate before generating

```bash
tablespec validate tables/
tablespec info tables/medical_claims/
```

Validation checks the UMF model, file layout, column naming, relationship
integrity, expectation compatibility, and pipeline completeness. A clean
result means this source-table contract is ready to compile.

## 3. Compile the ingest artifact

```bash
tablespec generate tables/medical_claims/ -f ingest > claims.ingest.sql
```

The generated SQL contains the raw landing table, the typed ingested table,
and the raw-to-ingested transform. For flat files, raw checks verify
castability and shape before values land in the typed table. For typed sources
such as JDBC and Parquet, tablespec skips string-shape checks that do not
apply.

```sql
CREATE TABLE raw_medical_claims (
  claim_id STRING,
  service_date STRING,
  billed_amount STRING
);

CREATE TABLE medical_claims (
  claim_id STRING NOT NULL,
  service_date DATE,
  billed_amount DECIMAL(12, 2)
);
```

## 4. Emit downstream project artifacts

```bash
tablespec emit tables/ out/dbt --backend dbt --dialect databricks
tablespec generate tables/medical_claims/ -f json > medical_claims.schema.json
tablespec validation-sync tables/medical_claims/ --out gx/
tablespec guidebook tables/ -o review/guidebook
```

The review surface is now a concrete set of generated files:

| Artifact | Why it matters |
|---|---|
| `claims.ingest.sql` | The exact raw-to-ingested transform |
| `out/dbt/models/medical_claims.sql` | The dbt model and contract generated from the UMF spec |
| `medical_claims.schema.json` | Machine-readable schema for integrations |
| `gx/medical_claims/suite.json` | Baseline validation generated from the same contract |
| `review/guidebook/index.html` | Static browsable review surface for tables, columns, validations, and lineage |

## 5. Hand off to silver

At this point ingested bronze is done. Silver can now make governed business
decisions: cross-source conformance, survivorship, entity resolution,
enrichment, and dimensional modeling. Those choices happen after the
source-table contract is complete, not hidden inside ingestion.

## Review checklist

- Source names are preserved.
- Types and nullability are declared.
- Keys and relationships are explicit.
- Validation is generated from the same UMF.
- The guidebook exposes tables, columns, validation rules, and lineage for review.
- Runtime artifacts are committed and reviewable.
