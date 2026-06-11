---
title: Universal Metadata Format
weight: 2
---

Universal Metadata Format (UMF) is the YAML-based schema format at the heart
of tablespec. Every tablespec operation begins with a UMF file.

## Structure

A UMF file declares a table's name, description, and columns:

```yaml
version: "1.0"
table_name: medical_claims
description: Healthcare claims — source-faithful ingested bronze
columns:
  - name: claim_id
    data_type: VARCHAR
    length: 50
    description: Unique claim identifier
    nullable:
      MD: false
      MP: false
  - name: billed_amount
    data_type: DECIMAL
    precision: 12
    scale: 2
    nullable:
      MD: true
      MP: true
```

## Column types

| UMF type | SQL equivalent | PySpark equivalent |
|----------|---------------|-------------------|
| `VARCHAR` | `VARCHAR(n)` | `StringType()` |
| `CHAR` | `CHAR(n)` | `StringType()` |
| `TEXT` | `TEXT` | `StringType()` |
| `INTEGER` | `INTEGER` | `IntegerType()` |
| `DECIMAL` | `DECIMAL(p,s)` | `DecimalType(p,s)` |
| `FLOAT` | `FLOAT` | `FloatType()` |
| `DATE` | `DATE` | `DateType()` |
| `DATETIME` | `TIMESTAMP` | `TimestampType()` |
| `BOOLEAN` | `BOOLEAN` | `BooleanType()` |

## Nullability per LOB

Nullability is declared per line-of-business because source feeds for Medicaid
(MD), Medicare (MP), and Medicare Advantage (ME) often have different population
patterns for the same column:

```yaml
nullable:
  MD: false   # Always present in Medicaid feed
  MP: true    # Sometimes omitted in Medicare feed
  ME: false   # Always present in Medicare Advantage feed
```

## Validation rules

Optional validation rules constrain values beyond type and nullability:

```yaml
- name: plan_type
  data_type: VARCHAR
  length: 2
  validation_rules:
    allowed_values: ["HMO", "PPO", "POS", "EPO"]
    min_length: 2
    max_length: 2
```

## Split-format UMF

For large schemas, UMF supports a directory-based split format where each
column is a separate file. tablespec auto-detects single-file or split-format
on load.
