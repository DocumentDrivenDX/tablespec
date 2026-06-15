---
ddx:
  id: ADR-017
---

# ADR-017: Machine-Readable Derivations Sheet for Lossless Excel Round-Trip

| Date | Status | Deciders | Related | Confidence |
|------|--------|----------|---------|------------|
| 2026-06-15 | Accepted | David Mautz | FEAT-009, ADR-005 | High |

## Context

| Aspect | Description |
|--------|-------------|
| Problem | The Excel converter (`src/tablespec/excel_converter.py`) round-trips structural column metadata, file format, validation rules, and relationships, but **dropped a column's `derivation`** on import. A column derived from multiple sources (`UMFColumnDerivation`: `strategy`, `candidates`, `survivorship`) lost its candidates, expressions, join filters, window-function options, strategy, and survivorship defaults whenever it passed UMF → Excel → UMF. Because `SQLPlanGenerator` (`src/tablespec/schemas/sql_generator.py`) compiles exactly these fields into gold SELECT SQL, an Excel-authored or Excel-edited derivation could not regenerate correct SQL — a silent fidelity hole in the "domain expert edits the spec in Excel" workflow. |
| Current State | The exporter wrote a human-oriented **"Survivorship"** sheet (`_create_survivorship_sheet`) using a hierarchical Level-1/Level-2 layout, `CellRichText`, and lossy packing: the source cell concatenates `table.column` or `table (instance).expression`, and `join_filter` is folded into the reason string. The importer (`ExcelToUMFConverter.convert`) had **no** derivation reader at all — it parsed only the legacy flat column fields `derivation_mapping` / `derivation_expression`. Separately, the domain-type data-validation dropdown inlined the full ~42-value option list (~515 chars) into the validation `formula1`, exceeding Excel's 255-char limit for inline list formulas — Excel reported the file as corrupt and silently stripped validations on open. |
| Requirements | FEAT-009 (Excel Bidirectional Conversion), FR-9.1–FR-9.4 — round-trip fidelity for the governed UMF surface. The derivation surface itself is the multi-source survivorship model unified under ADR-005. |
| Decision Drivers | Round-trip must be **lossless for every field `SQLPlanGenerator` consumes** (provable, not asserted); the human Survivorship sheet's presentation affordances (grouping, rich text) actively fight machine parsing; existing workbooks must keep importing unchanged; Excel must not declare generated files corrupt. |

## Decision

Add a dedicated, machine-readable **"Derivations" sheet** that the exporter
writes and the importer parses, keeping the existing "Survivorship" sheet as a
human-readable, presentation-only view that is never parsed back. Specifically:

1. **Separate Derivations sheet (one row per candidate).** Flat,
   header-addressed columns: `Column | Priority | Source Table | Source Column |
   Expression | Join Filter | Table Instance | Row Filter | Order By |
   Select Columns | Join Via | Reason | Derivation Strategy |
   Survivorship Strategy | Default Value | Default Condition |
   Survivorship Explanation`. The importer resolves columns by header name
   (reusing the `_build_header_index` pattern), so column order is irrelevant.
   Column-level fields are written on the column's first candidate row (or the
   single row of a candidate-less strategy/survivorship-only column).
2. **Two distinct strategy columns.** `Derivation Strategy` carries the
   top-level `UMFColumnDerivation.strategy` (`primary_key` / `base_column` /
   `max_across_sources`); `Survivorship Strategy` carries
   `survivorship.strategy` (e.g. `highest_priority`, `most_recent`). They drive
   different `SQLPlanGenerator` paths (`base.col` / `GREATEST` vs. the
   `COALESCE` survivorship ladder) and must never be conflated into one cell.
3. **JSON-encoded cells for list/nested fields.** `Order By` and
   `Select Columns` (lists) and `Join Via` (a nested `JoinViaSpec`) are
   `json.dumps`-encoded into a single cell — mirroring the existing
   `derivation_mapping` precedent the importer already `json.loads`es. A
   malformed JSON cell yields a benign review-note (surfaced in the import's
   `review_notes`), never a hard import failure.
4. **Back-compatible.** The importer guards on
   `if SHEET_DERIVATIONS in workbook.sheetnames`, so workbooks authored before
   this sheet existed import exactly as before (no `derivation` attached).
5. **Oversized-dropdown fix.** The domain-type dropdown now references a range
   on the hidden `_Instructions` sheet (`'_Instructions'!$P$2:$P$N`) instead of
   an inline list, matching the existing rule-type dropdown pattern, so no
   data-validation `formula1` exceeds Excel's 255-char limit.

**Key Points**: Losslessness is enforced by a **SQL-identity guard test** —
`generate_sql_plan` output is asserted byte-identical before vs. after an Excel
round-trip for a derived UMF exercising strategy, window options, join filters,
and survivorship defaults. The Survivorship sheet's format is unchanged; this
ADR adds a parallel machine sheet rather than repurposing it.

## Alternatives

| Option | Pros | Cons | Evaluation |
|--------|------|------|------------|
| Reverse-parse the existing human "Survivorship" sheet | One sheet; no new surface | Lossy/ambiguous packing (`table.column` vs. `table.expression` splits, `join_filter` buried in prose); two row levels need a stateful parser; `CellRichText` is not plain text — exact round-trip is impossible without changing the sheet | Rejected: cannot guarantee losslessness without degrading the human view |
| Flatten the Survivorship sheet into one round-trippable sheet | Single sheet, round-trippable | Destroys the deliberately human-oriented grouping/rich-text view and breaks its existing tests | Rejected: regresses the human-facing artifact |
| One combined "Strategy" column (heuristic routing) | Narrower sheet | Top-level vs. survivorship strategy are different model fields driving different SQL; a heuristic split is fragile and silently mis-routes `primary_key`/`base_column` into survivorship | Rejected: ambiguous and SQL-incorrect |
| **Separate machine-readable Derivations sheet + two strategy columns + JSON cells (selected)** | Exact, header-addressed round-trip; human Survivorship sheet untouched; back-compat via sheet-presence guard; provable via SQL-identity test | One extra sheet in the workbook; list/nested fields are JSON in a cell (not hand-friendly) | **Selected: only option that is lossless for the SQL-relevant surface while preserving the human sheet and back-compat** |

## Consequences

| Type | Impact |
|------|--------|
| Positive | A column's full derivation survives UMF → Excel → UMF; Excel-authored derivations regenerate byte-identical gold SQL (guard-tested); the human Survivorship sheet is unchanged; pre-existing workbooks import unchanged; generated workbooks no longer trip Excel's 255-char validation limit (no more "recovered/corrupt" prompt). |
| Negative | The workbook gains a second derivation-related sheet (machine vs. human), a minor authoring-surface duplication; `Order By` / `Select Columns` / `Join Via` are JSON-in-a-cell, which is less hand-editable than scalar columns. |
| Neutral | The unified expectation model (ADR-005) is unaffected; validation-rule, relationship, and file-format round-trips are unchanged. |

## Risks

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| A future `DerivationCandidate`/`Survivorship` field is added and silently dropped on round-trip | M | M | The SQL-identity guard test fails the moment a SQL-relevant field stops round-tripping; new fields get a Derivations column + a round-trip assertion |
| Hand-edited JSON cell (`Order By` / `Join Via`) is malformed | M | L | Importer emits a benign review-note naming the column + sheet field rather than failing the whole import |
| The two strategy columns are conflated by a future edit | L | M | Distinct headers + a round-trip test asserting top-level `derivation.strategy` lands on the derivation, not survivorship |
| Another long inline data-validation list is added later | L | M | The dropdown-range pattern (`_Instructions` ranges) is the established convention; a test guards that no inline `formula1` exceeds 255 chars |

## Validation

| Success Metric | Review Trigger |
|----------------|----------------|
| `generate_sql_plan` output is byte-identical before and after an Excel round-trip for a derived UMF | The SQL-identity guard test fails |
| A multi-candidate column with `join_filter`, window options, and survivorship defaults round-trips field-for-field | Any derivation round-trip assertion fails |
| `primary_key` / `max_across_sources` columns round-trip strategy on `derivation.strategy`, not survivorship | Strategy mis-routing observed |
| Workbooks without a Derivations sheet import with no `derivation` attached | A back-compat import test fails |
| No data-validation `formula1` exceeds 255 chars; Excel opens generated files without a repair prompt | The 255-char guard test fails, or Excel reports recovered content |

## Supersession

- **Supersedes**: None.
- **Superseded by**: None.

## Concern Impact

- **Concern selection**: This ADR does not select or change a project concern.
- **Practice override**: No library concern practice is overridden.
- **No concern impact**: The decision governs the Excel ↔ UMF derivation
  round-trip surface and a data-validation encoding fix; no active-concern
  relevance.

## References

- FEAT-009 (Excel Bidirectional Conversion) — FR-9.1–FR-9.4
- ADR-005 (unified expectation model — context for the survivorship/derivation surface)
- `src/tablespec/excel_converter.py` — `_create_derivations_sheet` (exporter),
  `_extract_derivations` + `convert()` merge (importer), `SHEET_DERIVATIONS`
  constant, `_Instructions` domain-type range (dropdown fix)
- `src/tablespec/models/umf.py` — `UMFColumnDerivation`, `DerivationCandidate`,
  `Survivorship`, `JoinViaSpec` (the round-tripped surface)
- `src/tablespec/schemas/sql_generator.py` — `SQLPlanGenerator` /
  `generate_sql_plan` (the consumer the round-trip must stay lossless for)
- `tests/unit/test_excel_converter.py` — `TestDerivationsRoundTrip` (field-level
  round-trip), `TestDerivationSqlIdentity` (byte-identical SQL guard),
  `TestDataValidationLimits` (255-char dropdown guard)

## Review Checklist

- [x] Context names a specific problem — derivation dropped on Excel import; SQL-relevant fidelity hole; 255-char dropdown corruption
- [x] Decision statement is actionable ("add a machine-readable Derivations sheet ... two strategy columns ... JSON-encoded cells ... dropdown range")
- [x] At least two alternatives were evaluated
- [x] Each alternative has concrete pros and cons
- [x] Selected option's rationale explains why it wins over the best alternative
- [x] Consequences include both positive and negative impacts
- [x] Negative consequences have documented mitigations
- [x] Risks are specific with probability and impact assessments
- [x] Validation defines how we'll know the decision was right
- [x] Review triggers define reconsideration conditions
- [x] Concern impact section complete (no impact)
- [x] ADR consistent with FEAT-009 and PRD FR-9.1–FR-9.4
