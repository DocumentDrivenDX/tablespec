---
ddx:
  id: FEAT-023
---

# FEAT-023: Authoring Tools

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-023
**Owner**: Platform / Data Engineering
**Covered PRD Subsystem(s)**: CLI Interface; LLM Prompt Generation; Domain Type Inference
**Covered PRD Requirements**: FR-8.1, FR-8.2, FR-6.2, FR-6.3, FR-14.4
**Cross-Subsystem Rationale**: Cross-subsystem authoring workflow: CLI mutations, prompt response application, validation preview, and domain assignment form one authoring surface.

## Description

CLI commands, LLM integration, validation preview, and interactive TUI for authoring and managing UMF schemas.

## Components

### CLI Mutation Commands (`src/tablespec/cli.py`)

Thin CLI wrappers around pure functions for scriptable UMF editing:

- `tablespec column add/modify/remove/rename` -- Column CRUD operations.
- `tablespec validation add/remove/sync` -- Manage expectations in the suite.
- `tablespec domain infer/set` -- Domain type inference and assignment.
- `tablespec apply-response` -- Apply LLM-generated validation rules.

Each command wraps a pure function. Test the function, not the CLI layer.

### LLM Response Applier (`src/tablespec/cli.py`)

Takes LLM-generated JSON (from prompt generators in `prompts/`), validates and integrates it into the UMF:

1. Validate GX expectation format.
2. Classify each expectation by stage via `classify_validation_type()`.
3. Deduplicate against existing expectations in the suite.
4. Validate that expectation types exist in GX.
5. If the UMF has `sample_values` on columns, run generated expectations against them via the GX test harness (FEAT-016) to check semantic correctness before accepting.
6. Return structured `ApplyResult`:

```python
@dataclass
class ApplyResult:
    added: list[Expectation]
    deduplicated: list[Expectation]   # Already existed
    invalid: list[dict]               # Failed validation
    warnings: list[str]
```

### Validation Preview (`src/tablespec/cli.py`)

- `tablespec preview` -- Show expectations classified by stage (raw/ingested), formatted as a table.
- `tablespec preview --against data.csv` -- Dry-run validation via GX DuckDB harness (FEAT-016 + ADR-006).
- `tablespec preview --diff` -- Run compatibility check against previous version (FEAT-022).

### Interactive TUI (`src/tablespec/tui.py`)

Textual-based terminal UI for browsing and editing UMF schemas:

- Tree view of tables -> columns with expandable details.
- Search across column names, descriptions, domain types.
- Relationship visualization between tables.
- Inline editing of column properties and expectations.

Requires adding `textual` as an optional dependency (`tablespec[tui]`). Testing via Textual's pilot framework.

NOTE: The TUI is for interactive exploration and editing. The CLI commands above are for scripting and CI. These are complementary, not overlapping.
## User Stories

- [US-036 — Author UMF with CLI and LLM Assistance](../user-stories/US-036-author-umf-with-cli-and-llm-assistance.md)

## Source

- `src/tablespec/cli.py` (existing, to be extended)
- `src/tablespec/prompts/` (existing prompt generators)

## Dependencies

- ADR-005 (unified expectation model for applier and preview)
- ADR-006 (DuckDB backend for preview --against)
- FEAT-016 (GX test harness)
- FEAT-017 (validation pipeline for staged execution)
- FEAT-022 (compatibility checker for preview --diff)
