---
ddx:
  id: US-001
---

# US-001: Load and Validate a UMF Schema from YAML

**Feature**: FEAT-001 — UMF Models and I/O
**PRD Requirements**: FR-1.1, FR-1.7, FR-1.8, FR-1.9
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer building a pipeline,
**I want** load a UMF schema from a YAML file and have it validated automatically,
**So that** I can trust the schema definition is correct before using it to generate DDL, configure data quality checks, or drive downstream processing.

## Context

This story covers the load and validate a umf schema from yaml slice in the parent feature. It exercises the parent feature requirements and stays within the linked PRD requirements without adding new runtime surface beyond the governing feature spec.

## Walkthrough

1. User starts from a load and validate a umf schema from yaml fixture or source object.
2. System runs the the UMF YAML load/validation flow runs for that fixture.
3. User reviews the generated or validated output as a normal artifact diff or test result.
4. System returns the expected artifact, validation result, or error shape for the slice.

## Acceptance Criteria

- [ ] **US-001-AC1** — Given a `tables/member/table.yaml` fixture with `member_id`, `plan_code`, and `nullable: false`, when the UMF YAML load/validation flow runs, then `load_umf_from_yaml(path)` returns a fully validated `UMF` object from a YAML file
- [ ] **US-001-AC2** — Given a `tables/member/table.yaml` fixture with `member_id`, `plan_code`, and `nullable: false`, when the UMF YAML load/validation flow runs, then Invalid column names (not matching `^[A-Za-z][A-Za-z0-9_]*$`), duplicate column names, and missing required fields raise clear validation errors
- [ ] **US-001-AC3** — Given a `tables/member/table.yaml` fixture with `member_id`, `plan_code`, and `nullable: false`, when the UMF YAML load/validation flow runs, then VARCHAR columns without a length and DECIMAL columns without precision produce appropriate warnings or errors
- [ ] **US-001-AC4** — Given a `tables/member/table.yaml` fixture with `member_id`, `plan_code`, and `nullable: false`, when the UMF YAML load/validation flow runs, then `save_umf_to_yaml(umf, path)` round-trips cleanly: saving and reloading produces an equivalent UMF object
- [ ] **US-001-AC5** — Given a `tables/member/table.yaml` fixture with `member_id`, `plan_code`, and `nullable: false`, when the UMF YAML load/validation flow runs, then Extra/unknown fields in the YAML are rejected (Pydantic `extra="forbid"`)
- [ ] **US-001-AC6** — Given a `tables/member/table.yaml` fixture with `member_id`, `plan_code`, and `nullable: false`, when the UMF YAML load/validation flow runs, then Per-LOB nullable configuration (MD, MP, ME) is preserved through load/save cycles

## Edge Cases

- **missing required fields**: missing required fields
- **duplicate columns or invalid names**: duplicate columns or invalid names
- **VARCHAR and DECIMAL defaults not supplied**: VARCHAR and DECIMAL defaults not supplied

## Test Scenarios

| Scenario | AC ID | Input / State | Action | Expected Result |
|----------|-------|---------------|--------|-----------------|
| Valid split table loads | US-001-AC1 | tables/member/table.yaml with member_id INTEGER, plan_code VARCHAR(12), nullable=false | the UMF YAML load/validation flow runs | `load_umf_from_yaml(path)` returns a fully validated `UMF` object from a YAML file |
| Bad member_id name is rejected | US-001-AC2 | column name "1member-id" in tables/member/columns/1member-id.yaml | the UMF YAML load/validation flow runs | Invalid column names (not matching `^[A-Za-z][A-Za-z0-9_]*$`), duplicate column names, and missing required fields raise clear validation errors |
| Missing VARCHAR and DECIMAL params | US-001-AC3 | plan_code VARCHAR and amount DECIMAL without length or precision | the UMF YAML load/validation flow runs | VARCHAR columns without a length and DECIMAL columns without precision produce appropriate warnings or errors |
| Member round-trip preserves fields | US-001-AC4 | saved `member` UMF written back to tables/member/table.yaml | the UMF YAML load/validation flow runs | `save_umf_to_yaml(umf, path)` round-trips cleanly: saving and reloading produces an equivalent UMF object |
| Unknown field is forbidden | US-001-AC5 | table.yaml includes extra field metadata.owner="qa" | the UMF YAML load/validation flow runs | Extra/unknown fields in the YAML are rejected (Pydantic `extra="forbid"`) |
| LOB nullable map survives | US-001-AC6 | nullable.md=false, nullable.mp=true, nullable.me=false | the UMF YAML load/validation flow runs | Per-LOB nullable configuration (MD, MP, ME) is preserved through load/save cycles |

## Dependencies

- **Stories**: None.
- **Feature Spec**: FEAT-001 — UMF Models and I/O
- **Feature Requirements**: UMF-01, UMF-02
- **PRD Requirements**: FR-1.1, FR-1.7, FR-1.8, FR-1.9
- **External**: Source fixtures, files, or local tooling as required by the story slice.

## Out of Scope

- authoring additional business rules beyond schema validation
- runtime generation of downstream artifacts

## Review Checklist

- [x] Stored as its own file `US-NNN-<slug>.md` (one file per story — never a single monolithic `user-stories.md`)
- [x] Covers one persona completing one goal, demonstrable end-to-end in a single flow
- [x] Links to its parent feature spec and names the PRD `FR-n` it covers
- [x] Every acceptance criterion is independently testable and carries a stable `US-NNN-ACm` ID
- [x] Walkthrough traces a complete path from trigger to outcome; at least one edge case documented
- [x] No exact API/CLI/event/schema/config/telemetry/adapter surface is defined inline; normative surface links to Contract artifacts
