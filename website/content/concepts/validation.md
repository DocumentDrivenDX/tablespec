---
title: Validation model
weight: 4
---

tablespec integrates with Great Expectations to validate DataFrames against
UMF contracts at load time.

## Baseline generation

`BaselineExpectationGenerator` converts a UMF schema into a Great Expectations
suite deterministically. Each column in the UMF produces a corresponding set
of expectations:

```python
from tablespec import load_umf_from_yaml
from tablespec.gx_baseline import BaselineExpectationGenerator

umf = load_umf_from_yaml("schema.yaml")
generator = BaselineExpectationGenerator(umf)
suite = generator.generate()
```

The generated suite is deterministic: the same UMF always produces the same
expectations. This means the suite can be committed alongside the UMF and
regenerated when the UMF changes.

## Constraint extraction

`GXConstraintExtractor` reverses the process: it reads an existing Great
Expectations suite and extracts constraints back into UMF format. This is
useful for bootstrapping UMF schemas from existing validated tables.

```python
from tablespec.gx_constraint_extractor import GXConstraintExtractor

extractor = GXConstraintExtractor(existing_suite)
umf = extractor.extract()
```

## Table validation

`TableValidator` (requires `tablespec[spark]`) validates a PySpark DataFrame
against a UMF schema using a generated Great Expectations suite:

```python
from tablespec import load_umf_from_yaml
from tablespec.validation import TableValidator

umf = load_umf_from_yaml("schema.yaml")
validator = TableValidator(umf, spark)
result = validator.validate(df)

if not result.success:
    print(result.failed_expectations)
```

## Validation scope

tablespec validates the ingested bronze contract: column presence, types,
nullability, and declared constraints. It does not validate business logic,
cross-table joins, or silver-layer transformations — those belong in
downstream validation pipelines with their own UMF schemas.
