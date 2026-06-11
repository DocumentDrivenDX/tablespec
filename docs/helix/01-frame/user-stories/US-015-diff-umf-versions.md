---
ddx:
  id: US-015
---

# US-015: Diff Two UMF Versions

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.1, FR-11.2
**Priority**: P1
**Status**: Approved

## Story

**As a** data engineer reviewing schema changes,
**I want** compare two UMF versions and see a structured list of differences,
**So that** I can understand what changed before approving a pull request.

## Acceptance Criteria

- [ ] **US-015-AC1** - `UMFDiff` detects added, removed, and modified columns
- [ ] **US-015-AC2** - Validation rule and metadata changes are identified separately
- [ ] **US-015-AC3** - `UMFChangeApplier` can apply individual changes to produce intermediate UMF versions
- [ ] **US-015-AC4** - Changes are typed (`UMFColumnChange`, `UMFMetadataChange`, `UMFValidationChange`)
