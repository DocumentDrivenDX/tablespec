---
ddx:
  id: US-015
---

# US-015: Diff Two UMF Versions

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.1, FR-11.2
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer reviewing schema changes,
**I want** compare two UMF versions and see a structured list of differences,
**So that** I can understand what changed before approving a pull request.

## Acceptance Criteria

- [ ] `UMFDiff` detects added, removed, and modified columns
- [ ] Validation rule and metadata changes are identified separately
- [ ] `UMFChangeApplier` can apply individual changes to produce intermediate UMF versions
- [ ] Changes are typed (`UMFColumnChange`, `UMFMetadataChange`, `UMFValidationChange`)
