---
ddx:
  id: US-014
---

# US-014: Generate Changelog from Git History

**Feature**: FEAT-010 — UMF Change Management
**PRD Requirements**: FR-11.3, FR-11.4, FR-11.5
**Priority**: P1
**Status**: Implemented

## Story

**As a** data governance lead,
**I want** generate a changelog of schema changes from git history,
**So that** I can track who changed what and when for audit and compliance purposes.

## Acceptance Criteria

- [ ] `ChangelogGenerator` produces structured entries from git commits in a table directory
- [ ] Each entry includes timestamp, author, change type, and affected components
- [ ] YAML diff parsing detects column, validation, metadata, and relationship changes
- [ ] `tablespec changelog` CLI command outputs formatted changelog
