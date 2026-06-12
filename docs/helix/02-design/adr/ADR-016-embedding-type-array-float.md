---
ddx:
  id: ADR-016
---

# ADR-016: Dimensioned EMBEDDING Logical Type Compiled to `ARRAY<FLOAT>`

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-12 | Accepted | Erik LaBianca | FEAT-032, FEAT-031, ADR-015, ADR-013 | High |

> **Planning status.** The decision is final (operator-confirmed
> 2026-06-12); nothing here is implemented yet. FEAT-032 owns the
> feature-side requirements; consumer touchpoints below are the planned
> change surface, cited as they exist today.

## Context

| Aspect | Description |
|--------|-------------|
| Problem | UMF's type alphabet is a closed 10-type set enforced by a regex pattern (`data_type`, `src/tablespec/models/umf.py:511`: `VARCHAR\|DECIMAL\|INTEGER\|DATE\|DATETIME\|TIMESTAMP\|BOOLEAN\|TEXT\|CHAR\|FLOAT`). An embedding column — a fixed-dimension vector of floats per row, the core column of any document-corpus table — cannot be declared at all. Mis-speccing it as TEXT/VARCHAR would attract string-shape expectations (`gx_baseline.py`) and string profiling, both meaningless against a vector; leaving it out of the spec abandons the single-source-of-truth contract for exactly the column the corpus exists to carry. |
| Current State | Every type-driven consumer branches on the closed alphabet: the type-mapping functions (`src/tablespec/type_mappings.py` — `map_to_gx_spark_type`:109, `map_to_pyspark_type`:157, `map_to_json_type`:204, `map_to_pyspark_type_obj`:233), the schema generators (`src/tablespec/schemas/generators.py` — `generate_sql_ddl`:43, `generate_pyspark_schema`:119, `generate_json_schema`:174), baseline expectation generation (`src/tablespec/gx_baseline.py` — `STRING_SHAPE_EXPECTATION_TYPES`:41-58, `generate_baseline_column_expectations`:365), sample-data generation (`src/tablespec/sample_data/column_value_generator.py:77`), and the compatibility checker plus its widening lattice (`src/tablespec/compatibility.py` — `_check_type_change`:108, `check_compatibility`:341; `src/tablespec/type_lattice.py` — `is_safe_widening`:21). None of them has a vector concept. |
| Requirements | PRD FR-1.11 (EMBEDDING type — being added to FR-1 in parallel by the PRD owner; FR-1.10 is the last entry today). FEAT-032 EMB-01..09. PRD Non-Goal preserved: tablespec never parses documents or calls embedding models. |
| Decision Drivers | Research-backed target facts (2026-06-12): Databricks has **no native VECTOR type** — the March 2026 DBSQL vector functions (`vector_cosine_similarity` etc.) all operate on `ARRAY<FLOAT>`; Vector Search self-managed embeddings require an `array<float>` source column plus a primary key and Change Data Feed (standard endpoints), and storage-optimized endpoints require `dimension % 16 == 0`; `databricks-gte-large-en` returns 1024-dim floats; Lakebase (managed Postgres, GA 2026) offers pgvector's `vector(n)` — a *declared* dimension keeps that future target open. Smallest viable blast radius across the type lattice, compatibility checker, sample data, and casting. Dimensionality must be validatable (the data-quality point of speccing the column at all). |

## Decision

We will add a **dimensioned logical `EMBEDDING` type** to UMF:
`data_type: EMBEDDING` plus a **required `dimension: <int>`** column
property (≥ 1; required for EMBEDDING, rejected on any other type).

1. **Compilation targets** — `EMBEDDING(dim)` compiles to `ARRAY<FLOAT>`
   in Spark SQL / Delta DDL (`generate_sql_ddl`,
   `schemas/generators.py:43`), `ArrayType(FloatType())` in PySpark
   schemas (`generate_pyspark_schema`:119, `map_to_pyspark_type`:157,
   `map_to_pyspark_type_obj`:233), and a JSON Schema array-of-number
   with `minItems`/`maxItems` pinned to the declared dimension
   (`generate_json_schema`:174, `map_to_json_type`:204).
2. **Validation** — the GX baseline gains a dimensionality expectation
   for EMBEDDING columns: every non-NULL value has exactly `dimension`
   elements, with no NULL/NaN elements inside unless declared. A
   **non-blocking advisory** fires when `dimension % 16 != 0` (the
   storage-optimized Vector Search constraint). EMBEDDING columns are
   **excluded** from string-shape checks
   (`STRING_SHAPE_EXPECTATION_TYPES`, `gx_baseline.py:41-58`) and from
   profiling statistics beyond null counts and observed-dimension facts.
3. **Sample data** — deterministic pseudo-embeddings: seeded unit
   vectors of the declared dimension
   (`sample_data/column_value_generator.py:77` grows an EMBEDDING
   branch), keeping the committed-artifact determinism contract.
4. **Compatibility** — `EMBEDDING(n)` is compatible only with
   `EMBEDDING(n)`. A dimension change is a **breaking** change
   (`compatibility.py:_check_type_change`:108); the widening lattice
   (`type_lattice.py:8-21`) gains no edges to or from EMBEDDING.
5. **The dimension is per-spec data, not library config** — newer
   foundation models may emit different dimensions; the spec declares
   what the table carries, and validation enforces it.

**Key Points**: This extends the FR-1 type system; it does not
generalize it — generic `ARRAY<T>` is explicitly rejected (below). The
document-corpus table shape (doc_id, chunk_id, source_path/page, text,
embedding, provenance) is a spec **pattern** under FEAT-032 (CORP
family), not new model fields. Acquisition (PDF/HTML parsing, chunking,
embedding-model calls) stays **consumer plumbing** — the same boundary
ADR-015 drew for the SQL Server install in the Northwind demo.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Generic `ARRAY<T>` element-typed container | One mechanism covers embeddings and future array needs; closer to Spark's own type system | Far larger blast radius for no demo benefit: every consumer of the closed alphabet — type lattice widenings, compatibility checks, sample-data generators, the cast layer (`casting_utils.py`), JSON/DDL/PySpark emitters — must handle arbitrary element types and nesting; dimensionality still needs a separate property; no current requirement needs any element type but FLOAT | Rejected: pays the full container-type tax to ship one float-vector column |
| Compile to a native VECTOR target type | Self-describing target column; index-friendly | **Does not exist on Databricks** — the 2026 DBSQL vector functions operate on `ARRAY<FLOAT>`, and Vector Search consumes `array<float>` source columns; emitting VECTOR would produce DDL no target accepts | Rejected: targets a type the platform does not have |
| Undimensioned `ARRAY<FLOAT>` (no `dimension` property) | Smallest model diff; no new column property | Cannot validate dimensionality (the data-quality point of the type); cannot target pgvector `vector(n)` on Lakebase later; cannot check the storage-optimized `% 16` constraint; a model upgrade that changes dimension becomes silently compatible | Rejected: discards exactly the metadata a spec tool exists to hold |
| **Dimensioned EMBEDDING → `ARRAY<FLOAT>` (selected)** | Honest logical type with the one property that matters; validatable dimensionality; `% 16` advisory checkable; pgvector `vector(n)` target stays open; blast radius confined to one new alphabet entry per consumer | A logical type that several physical targets render identically (`ARRAY<FLOAT>`), so DDL alone cannot round-trip it back to EMBEDDING — the UMF stays the source of truth | **Selected: validates what matters, targets what exists, keeps what's coming open** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | Corpus tables become fully speccable — including their defining column; dimensionality is enforced as data quality, not hoped for; the `% 16` and PK/CDF Vector Search prerequisites surface at spec time instead of at index-creation failure; sample data for EMBEDDING columns is deterministic; a model-upgrade dimension change is caught as a breaking change by the compatibility checker. |
| Negative | Every consumer that branches on the type alphabet must add an EMBEDDING arm (the full list in Current State); `ARRAY<FLOAT>` DDL is not self-describing as an embedding, so reverse engineering (discovery, GX constraint extraction) cannot recover EMBEDDING from the physical type alone; the JSON Schema `minItems`/`maxItems` rendering makes dimension changes schema-visible (intended, but a diff source). |
| Neutral | ADR-007's all-STRING raw landing is untouched — corpus tables land typed (parquet/JSON per ADR-015), not text-landed; the FEAT-031 `json` source kind (operator-decided 2026-06-12, recorded in FEAT-031) carries the XBRL facts side of the demo and is independent of this type decision. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| Embedding-model dimension drift — newer FM models change output dimension (e.g. a gte successor ≠ 1024) | M | M | The dimension is **per-spec data**, validated: the dimensionality expectation fails loudly on mismatched data, and a spec dimension change is a breaking change per the compatibility checker — never a silent re-dimension |
| String-shape or numeric profiling logic reaches EMBEDDING columns | M | M | EMBEDDING is excluded at suite-composition time (the `STRING_SHAPE_EXPECTATION_TYPES` seam, `gx_baseline.py:41-58`) and at profiling-phase selection (`native_profiler.py:296-301` per-type phases); a conformance fixture with an EMBEDDING column asserts zero string-shape expectations emitted |
| `% 16` advisory misread as a validation failure | L | L | Advisory is non-blocking by construction and labeled as the storage-optimized Vector Search constraint; standard endpoints have no such constraint |
| Sample pseudo-embeddings accidentally nondeterministic (float formatting, seed scope) | L | M | Seeded generation with pinned formatting; golden-artifact diff gate covers a fixture with an EMBEDDING column |
| Float precision mismatch (FLOAT32 vs DOUBLE) between endpoint output and `ARRAY<FLOAT>` landing | L | L | `FloatType()` matches Vector Search's `array<float>` requirement; the landing cast is a narrowing the corpus pattern documents |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| SEC 10-K demo (US-045) green on Databricks: corpus table specced with `EMBEDDING(1024)`, dimensionality expectation passes on real and fake embeddings | Any US-045 AC failing on the workspace lane |
| Zero string-shape expectations emitted for EMBEDDING columns (conformance fixture) | A string-shape check observed in a suite for an EMBEDDING column |
| Deterministic sample embeddings — byte-identical across runs | Any golden-artifact diff on an unchanged EMBEDDING fixture |
| Dimension change flagged breaking by `check_compatibility` | A dimension change passing as compatible |
| Existing UMFs (no EMBEDDING columns) recompile byte-identically | Any golden diff on a pre-existing UMF |
| Databricks ships a native VECTOR type or vector functions stop accepting `ARRAY<FLOAT>` | Reopen the target-type question |

## Supersession

- **Supersedes**: None. This ADR **extends the FR-1 type system** with
  one new logical type; ADR-007 (all-STRING raw, text-landed sources)
  and ADR-015 (kind-dependent raw typing) are unchanged — corpus tables
  land typed under ADR-015's existing contract.
- **Superseded by**: None

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden.
- **No concern impact**: This ADR governs the UMF type alphabet and its
  compilation targets; no active-concern relevance.

## References

- Research sources (2026-06-12):
  - DBSQL 2026 release notes — vector functions operate on `ARRAY<FLOAT>`:
    <https://docs.databricks.com/gcp/en/sql/release-notes/2026>
  - Vector Search — self-managed embeddings require `array<float>` source
    columns, PK, Change Data Feed; storage-optimized requires
    `dimension % 16 == 0`:
    <https://docs.databricks.com/aws/en/generative-ai/create-query-vector-search>
  - Foundation Model APIs — `databricks-gte-large-en`, 1024-dim float
    output:
    <https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models>
  - Lakebase GA — managed Postgres with pgvector `vector(n)`:
    <https://databricks.com/blog/databricks-lakebase-generally-available>
- PRD FR-1 type-system family (FR-1.2 lists the 10 current types;
  FR-1.11 being added in parallel); PRD Non-Goal: no document parsing or
  model calls in tablespec
- FEAT-032 (Embeddings and Document Corpus — feature-side owner),
  US-045 (SEC 10-K corpus + facts acceptance story), FEAT-031 (`json`
  source kind for the facts table; recorded there)
- Consumers to touch: `src/tablespec/models/umf.py:511` (the `data_type`
  pattern), `src/tablespec/type_mappings.py` (`map_to_gx_spark_type`:109,
  `map_to_pyspark_type`:157, `map_to_json_type`:204,
  `map_to_pyspark_type_obj`:233),
  `src/tablespec/schemas/generators.py` (`generate_sql_ddl`:43,
  `generate_pyspark_schema`:119, `generate_json_schema`:174),
  `src/tablespec/gx_baseline.py` (`STRING_SHAPE_EXPECTATION_TYPES`:41-58,
  `generate_baseline_column_expectations`:365),
  `src/tablespec/sample_data/` (`column_value_generator.py:77`),
  `src/tablespec/compatibility.py` (`_check_type_change`:108,
  `check_compatibility`:341), `src/tablespec/type_lattice.py`
  (`is_safe_widening`:21)
- ADR-015 (consumer-plumbing boundary precedent: SQL Server install
  stayed with the consumer bundle), ADR-013 (target-agnostic core seam
  the new mappings live behind)

## Review Checklist

- [x] Context names a specific problem — closed 10-type alphabet, no
  vector concept in any type-driven consumer
- [x] Decision statement is actionable ("we will add a dimensioned
  logical `EMBEDDING` type ... compiled to `ARRAY<FLOAT>`")
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best
  alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete (no impact)
- [x] ADR consistent with FEAT-032, FEAT-031 (`json` kind), and the PRD
  Non-Goal on document parsing / model calls
- [x] Planned-work honesty: nothing claimed implemented
