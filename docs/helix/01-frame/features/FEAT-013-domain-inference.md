---
ddx:
  id: FEAT-013
---

# FEAT-013: Domain Type Inference

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-013
**Owner**: Data Platform
**Covered PRD Subsystem(s)**: Domain Type Inference
**Covered PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Automatic detection of domain types (e.g., us_state_code, email, phone_number) from column names, descriptions, and sample values. Used in spec generation to tag columns for downstream validation and sample data.

## Components

### Domain Type Registry (`inference/domain_types.py`)
- `DomainTypeRegistry` - YAML-driven registry of domain types with patterns and validation rules
- Default registry path relative to module
- Lookup by name and pattern matching

### Domain Type Inference (`inference/domain_types.py`)
- `DomainTypeInference` - Infer domain types from column metadata
- Name-based matching (regex patterns on column names)
- Description-based matching
- Sample value validation
## User Stories

- [US-017 — Infer Domain Types for Columns](../user-stories/US-017-infer-domain-types.md)

## Source

- `src/tablespec/inference/domain_types.py`
