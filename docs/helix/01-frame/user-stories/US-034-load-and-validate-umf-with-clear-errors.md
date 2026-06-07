---
ddx:
  id: US-034
---

# US-034: Load and Validate UMF with Clear Errors

**Feature**: FEAT-021 - UMF Loader & Validator Improvements
**Feature Requirements**: LOAD-01, VALID-01, PROP-01
**PRD Requirements**: FR-1.7, FR-10.2, FR-10.3
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer fixing malformed UMF files
**I want** loader and validator errors to identify the failing path, column file, and expectation type
**So that** I can repair specs quickly instead of debugging generic parse failures

## Context

This story connects loader diagnostics, expectation validation, and split-format roundtrip hardening to the UMF I/O and Split-Format PRD families.

## Walkthrough

1. User loads a malformed split-format or JSON UMF.
2. System reports the missing/malformed file or invalid expectation type with context.
3. User fixes the specific input and re-runs the loader.

## Acceptance Criteria

- [ ] **US-034-AC1** - Given malformed split-format inputs, when `UMFLoader` runs, then errors name the missing or invalid file and expected structure.
- [ ] **US-034-AC2** - Given valid UMF objects, when saved and loaded through split format, then roundtrip preserves fields across generated cases.

## Edge Cases

- **Empty table file**: loader reports malformed table metadata, not only format detection failure.
- **Unknown expectations**: validator warns or reports according to compatibility policy.

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Loader diagnostics | US-034-AC1 | malformed split dir | load UMF | targeted error |
| Split roundtrip | US-034-AC2 | generated UMF | save/load split | equivalent object |

## Dependencies

- **Feature Spec**: FEAT-021
- **PRD Requirements**: FR-1.7, FR-10.2, FR-10.3

## Out of Scope

- Changing the UMF schema format.
