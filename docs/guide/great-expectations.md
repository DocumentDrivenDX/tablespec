# Great Expectations Integration

tablespec integrates with Great Expectations for baseline expectation generation, constraint extraction, and UMF-to-GX mapping.

## Baseline Expectation Generation

Generate deterministic expectations from UMF metadata:

```python
from tablespec import BaselineExpectationGenerator, load_umf_from_yaml

# Load UMF
umf = load_umf_from_yaml("examples/schema.yaml")
umf_dict = umf.model_dump()

# Generate baseline expectations
generator = BaselineExpectationGenerator()
expectations = generator.generate_baseline_expectations(
    umf_dict,
    include_structural=True
)

# Expectations include:
# - Structural: column count and ordered column list (include_structural)
# - Nullability (per-context row_condition checks when applicable)
# - Length constraints
# - Cast and date/timestamp format checks
# - Cross-column date-range ordering
# - Domain-type expectations (from column domain_type)
# - Profiling-derived expectations when profiling data is attached
```

Column-existence and column-type expectations are intentionally not generated —
they are redundant with schema metadata, which the compiled DDL and schemas
already enforce.

## Constraint Extraction

Extract usable constraints from an existing expectation suite (UMF validation
rules or a standalone suite file) — value sets, regex patterns, strftime
formats, max lengths, and not-null flags:

```python
from tablespec import GXConstraintExtractor

extractor = GXConstraintExtractor()

# Load the suite for a table (UMF validation rules first, then standalone files)
expectations = extractor.load_expectations_for_table("my_table", relationships_dir)

# Extract constraints
value_sets = extractor.extract_value_sets(expectations)
regex_patterns = extractor.extract_regex_patterns(expectations)
strftime_formats = extractor.extract_strftime_formats(expectations)

# Or query a single column
allowed_values = extractor.get_constraints_for_column(expectations, "state_cd")
```

## UMF to Great Expectations Mapping

Generate a complete GX expectation suite from a UMF file:

```python
from tablespec import UmfToGxMapper

mapper = UmfToGxMapper()
suite = mapper.generate_expectations("tables/my_table.umf.yaml", strictness="medium")
# suite is a dict: {"name": "...", "meta": {...}, "expectations": [...]}
```

`strictness` accepts `"loose"`, `"medium"`, or `"strict"`.
