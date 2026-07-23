---
ddx:
  id: US-042
---

# US-042: Dump-Dialect Text Landing (Story Floor)

**Feature**: FEAT-031 — Multi-Source Ingestion (Source-Shape Contract)
**Feature Requirements**: DUMP-01, DUMP-02, DUMP-03, DUMP-04
**PRD Requirements**: FR-21.2
**Priority**: P1
**Status**: Built (implementation shipped; this story backfills AC floor)

## Story

**As a** data engineer landing database dump files
**I want** delimited sources to honor multi-character line terminators,
null escapes, footer rows, and skip rows
**So that** dump dialects compile and read without silent mis-parses.

## Context

DUMP-01..04 are **shipped** (model options + dump reader). Implement child
`tablespec-7ec86390` is closed. This story only records AC evidence.

## Walkthrough

1. Author declares dump options on a `source: {kind: delimited, …}` block.
2. Dump reader normalizes skip/footer/null_escape/line_terminator.
3. Unit tests assert record materialization matches expected rows.

## Acceptance Criteria

- [x] **US-042-AC1 (DUMP-01 multi-character line terminator)** — Given a
  delimited source with a multi-character `line_terminator`, when dump records
  are read, then records split on that terminator.
  **Evidence**: `tests/unit/test_ingestion_package.py`
  (`test_dump_reader_normalizes_skip_footer_and_null_escape`,
  `test_dump_reader_uses_normalized_records`).
- [x] **US-042-AC2 (DUMP-02 null escape)** — Given `null_escape: "\\N"`, when
  a field equals that token, then the landed value is null/empty per reader
  contract.
  **Evidence**: same dump reader tests (fixture rows with `\\N`).
- [x] **US-042-AC3 (DUMP-03 footer rows)** — Given `footer_rows: N`, when
  dump records are read, then the last N records are excluded from data.
  **Evidence**: same dump reader tests (`footer_rows=1`).
- [x] **US-042-AC4 (DUMP-04 skip_rows)** — Given `skip_rows: N`, when dump
  records are read, then the first N lines are skipped before header/data.
  **Evidence**: same dump reader tests (`skip_rows=2`).

## Edge Cases

- Headerless dumps require synthesized metadata columns in backbone/conformance
  loaders (not re-tested here; covered by backbone delimited quirks path).

## Dependencies

- **Feature Spec**: FEAT-031
- **Work**: bead `tablespec-e322b612` (story floor only)
