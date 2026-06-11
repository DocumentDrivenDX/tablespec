---
ddx:
  id: FEAT-020
---

# FEAT-020: Domain Type System Improvements

**Status**: Approved
**Priority**: P1
**Feature ID**: FEAT-020
**Owner**: Data Platform
**Covered PRD Subsystem(s)**: Domain Type Inference
**Covered PRD Requirements**: FR-14.1, FR-14.2, FR-14.3, FR-14.4
**Cross-Subsystem Rationale**: None — single subsystem.

## Description

Improvements to the domain type inference system for better matching accuracy, richer results, and consistency across the codebase.

## Components

### Abbreviation Expansion (`src/tablespec/inference/domain_types.py`)

`COMMON_ABBREVIATIONS` dict mapping healthcare data abbreviations to full words:

```python
COMMON_ABBREVIATIONS = {
    "mbr": "member", "dt": "date", "cd": "code", "desc": "description",
    "nm": "name", "addr": "address", "nbr": "number", "amt": "amount",
    "qty": "quantity", "pct": "percent", "ind": "indicator", "typ": "type",
    "sts": "status", "eff": "effective", "exp": "expiration", ...
}
```

`expand_column_name()` generates candidate names for fuzzy matching, improving inference accuracy on abbreviated column names like `mbr_eff_dt` -> `member_effective_date`.

### Confidence-Ranked Results with Explanation (`src/tablespec/inference/domain_types.py`)

`infer_domain_type()` currently returns `tuple[str | None, float]` (type + confidence). Replace this with a structured `InferenceResult` that adds explanation and runner_up fields:

```python
@dataclass
class InferenceResult:
    domain_type: str        # Best match
    confidence: float       # 0.0 - 1.0
    explanation: str        # Which signals matched (name pattern, value regex, etc.)
    runner_up: str | None   # Second-best match for ambiguous cases
```

### Excel Converter Registry Sync (`src/tablespec/excel_converter.py`)

Excel dropdown for domain types currently reads from a hardcoded 14-type list. Update to read from `DomainTypeRegistry` instead, making all 41+ domain types available in the Excel authoring workflow.

### Regex Validation on Registry Load (`src/tablespec/inference/domain_types.py`)

Invalid regex patterns in `domain_types.yaml` currently fail silently during inference. Change to raise `ValueError` on registry load, catching configuration errors early.
## User Stories

- [US-033 — Improve Domain Type Inference](../user-stories/US-033-improve-domain-type-inference.md)

## Source

- `src/tablespec/inference/domain_types.py`
- `src/tablespec/excel_converter.py`
