---
ddx:
  id: US-002
---

# US-002: Construct a UMF Schema Programmatically

**Feature**: FEAT-001 — UMF Models and I/O
**PRD Requirements**: FR-1.1, FR-1.2, FR-1.3, FR-1.5, FR-1.6, FR-1.10
**Priority**: P1
**Status**: Approved

## Story

**As a** platform engineer managing schema standards,
**I want** construct UMF schemas programmatically using type-safe Python models,
**So that** I can generate and manage table specifications across Medicaid, Medicare Part D, and Medicare lines of business in automated workflows without hand-editing YAML.

## Context

This story covers the construct a umf schema programmatically slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a construct a umf schema programmatically fixture or source object.
2. System runs the the programmatic UMF construction flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-002-AC1** — Given `UMF(table_name="member", columns=[UMFColumn(name="member_id", data_type="INTEGER", nullable=False)])`, when the programmatic UMF construction flow runs, then `UMF`, `UMFColumn`, `Nullable`, `ValidationRules`, `Relationships`, and `UMFMetadata` can be instantiated with keyword arguments and compose into a complete schema
- [ ] **US-002-AC2** — Given `UMFColumn(name="1member-id", data_type="INTEGER", nullable=False)`, when the programmatic UMF construction flow runs, then Pydantic rejects the invalid column name immediately and reports the failing `name` field
- [ ] **US-002-AC3** — Given `ForeignKey(column="member_id", references="member.member_id", confidence=0.82, legacy_format="ref_table.ref_col")`, when the programmatic UMF construction flow runs, then confidence scoring and legacy format support work when building relationships programmatically
- [ ] **US-002-AC4** — Given `member_umf = UMF(table_name="member", columns=[UMFColumn(name="member_id", data_type="INTEGER", nullable=False)])`, when the programmatic UMF construction flow runs, then `save_umf_to_yaml(member_umf, tmp_path / "member.yaml")` serializes the constructed UMF object for storage or distribution

## Edge Cases

- **invalid column name member_id starting with a digit**: column name `1member-id` starting with a digit
- **legacy relationship metadata with confidence 0.82**: `ForeignKey(column="member_id", references="member.member_id", confidence=0.82)`
- **serialized YAML path tmp_path / "member.yaml"**: serialized YAML path `tmp_path / "member.yaml"`

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Compose a member UMF object | US-002-AC1 | `UMF(table_name="member", columns=[UMFColumn(name="member_id", data_type="INTEGER", nullable=False)])` | the programmatic UMF construction flow runs | `UMF`, `UMFColumn`, `Nullable`, `ValidationRules`, `Relationships`, and `UMFMetadata` can be instantiated with keyword arguments and compose into a complete schema |
| Reject a bad column name | US-002-AC2 | `UMFColumn(name="1member-id", data_type="INTEGER", nullable=False)` | the programmatic UMF construction flow runs | Pydantic rejects the invalid column name immediately and reports the failing `name` field |
| Build legacy FK metadata | US-002-AC3 | `ForeignKey(column="member_id", references="member.member_id", confidence=0.82, legacy_format="ref_table.ref_col")` | the programmatic UMF construction flow runs | confidence scoring and legacy format support work when building relationships programmatically |
| Serialize the constructed UMF | US-002-AC4 | `member_umf = UMF(table_name="member", columns=[UMFColumn(name="member_id", data_type="INTEGER", nullable=False)])` and `tmp_path / "member.yaml"` | the programmatic UMF construction flow runs | `save_umf_to_yaml(member_umf, tmp_path / "member.yaml")` serializes the constructed UMF object for storage or distribution |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-001 — UMF Models and I/O
- **Feature Requirements**: UMF-01, UMF-02
- **PRD Requirements**: FR-1.1, FR-1.2, FR-1.3, FR-1.5, FR-1.6, FR-1.10
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- file loading and split-format conversion
- downstream DDL or suite generation

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
