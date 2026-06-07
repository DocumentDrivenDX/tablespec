---
ddx:
  id: FEAT-012
---

# FEAT-012: Quality Baselines

**Status**: Implemented
**Priority**: P1
**Feature ID**: FEAT-012
**Owner**: Data-Quality Platform
**Covered PRD Subsystem(s)**: Quality Baselines
**Covered PRD Requirements**: FR-13.1, FR-13.2, FR-13.3, FR-13.4, FR-13.5
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Capture, store, and compare quality baselines from DataFrames for drift detection. Requires PySpark.

## Components

### Baseline Service (`quality/baseline_service.py`) [requires PySpark]
- `BaselineService.capture()` - Capture row counts, column distributions, numeric stats
- `BaselineService.compare()` - Compare current vs previous baseline
- Jensen-Shannon divergence for distribution drift

### Baseline Storage (`quality/baseline_storage.py`)
- `RunBaseline`, `ColumnDistribution`, `NumericStats` models
- `RowCountComparison`, `DistributionComparison`, `RecordComparison` comparison models
- `BaselineWriter` for persistence

### Executor (`quality/executor.py`)
- Quality check execution against baselines

### Sync Baseline (`sync_baseline.py`)
- Synchronize metadata columns and baseline validations across table definitions
- Idempotent operation preserving user customizations
- Conflict detection for modified rule content
## User Stories

- [US-016 — Capture and Compare Quality Baselines](../user-stories/US-016-capture-quality-baseline.md)
- [US-019 — Sync Baseline Validations Across Tables](../user-stories/US-019-sync-baselines.md)

## Source

- `src/tablespec/quality/`
- `src/tablespec/sync_baseline.py`
