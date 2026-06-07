---
ddx:
  id: US-001
---

# US-001: Load and Validate a UMF Schema from YAML

**Feature**: FEAT-001 — UMF Models and I/O
**PRD Requirements**: FR-1.1, FR-1.7, FR-1.8, FR-1.9
**Priority**: P1
**Status**: Implemented

## Story

**As a** data engineer building a pipeline,
**I want** load a UMF schema from a YAML file and have it validated automatically,
**So that** I can trust the schema definition is correct before using it to generate DDL, configure data quality checks, or drive downstream processing.

## Acceptance Criteria

- [ ] `load_umf_from_yaml(path)` returns a fully validated `UMF` object from a YAML file
- [ ] Invalid column names (not matching `^[A-Za-z][A-Za-z0-9_]*$`), duplicate column names, and missing required fields raise clear validation errors
- [ ] VARCHAR columns without a length and DECIMAL columns without precision produce appropriate warnings or errors
- [ ] `save_umf_to_yaml(umf, path)` round-trips cleanly: saving and reloading produces an equivalent UMF object
- [ ] Extra/unknown fields in the YAML are rejected (Pydantic `extra="forbid"`)
- [ ] Per-LOB nullable configuration (MD, MP, ME) is preserved through load/save cycles
