---
ddx:
  id: US-020
---

# US-020: Resolve Pipeline Dependencies

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.1
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer working with cross-pipeline table references,
**I want** validate dependency versions and detect cycles,
**So that** pipeline ordering is correct and version constraints are satisfied.

## Acceptance Criteria

- [ ] `dependency_resolver.py` loads pipeline dependencies from metadata
- [ ] Version constraint validation against packaging specifiers
- [ ] Cycle detection in dependency graph
- [ ] Clear error reporting for unresolved or conflicting dependencies
