---
title: Raw, ingested, and silver
weight: 1
---

tablespec governs the boundary between raw source data and the downstream
layers that build on it. Understanding where each layer begins and ends is
essential to using tablespec correctly.

## The three layers

### Raw

Raw is the data as it arrives from the source system — files, API payloads,
CDC streams, or database exports. Raw has no contract: column names are whatever
the source produces, types are whatever the transport format carries, and
nullability is unverified.

Raw is the ground truth for auditing and replay. It is not the foundation you
build business logic on.

### Ingested bronze

Ingested bronze is where tablespec operates. The ingested layer:

- **Preserves source semantics.** Column names match the source field names.
  Types reflect what the source system produces, not a downstream preference.
  Nullability is declared based on the source feed's actual behavior, not on
  what downstream consumers would prefer.
- **Is governed by a UMF schema.** Every column has a declared type,
  nullability per LOB (MD/MP/ME for Medicaid/Medicare), and optional validation
  rules. The UMF is the contract.
- **Is validated on load.** Great Expectations suites generated from UMF verify
  that each load conforms to the declared contract before data flows downstream.

The ingested layer is the stable foundation. If something is wrong with the
data, you can trace it back to the source semantics preserved here rather than
guessing whether the problem was introduced by a conformance transform.

### Silver

Silver is where cross-source work begins. The silver layer applies
transformations that require judgment beyond what the source system provides:

- **Cross-source conformance**: aligning the same concept across multiple
  source systems (e.g., standardizing member ID formats from three different
  payers).
- **Survivorship**: choosing which version of a record to keep when duplicates
  or conflicts exist across sources.
- **Entity resolution**: linking records that refer to the same real-world
  entity but arrive with different identifiers.
- **Enrichment**: adding derived or externally sourced attributes that extend
  the source data.
- **Dimensional modeling**: restructuring data for analytical consumption
  (facts, dimensions, slowly changing dimensions).

Silver is intentionally separate from ingested bronze because these
transformations make choices that must be governed explicitly. A silver table
is not source-faithful — it represents a business decision.

## Why the boundary matters

Most ingestion pipelines blur the boundary between ingested and silver.
Column renaming, type casting, and null-coalescing happen in the same job that
reads from the source. When something downstream breaks, it is hard to tell
whether the problem is in the source data or in a transform applied at
ingestion.

tablespec enforces the separation. The ingested layer is a faithful mirror of
the source — no renames, no type promotions, no nullability assumptions beyond
what the source feed actually exhibits. Silver transformations are separate jobs
with their own contracts.

## In practice

A tablespec UMF schema for an ingested bronze table looks like this:

```yaml
version: "1.0"
table_name: member_eligibility
description: Member eligibility — source-faithful ingested bronze from claims feed
columns:
  - name: mbr_id          # Source column name, not a standardized version
    data_type: VARCHAR
    length: 20
    nullable:
      MD: false
      MP: false
  - name: elig_start_dt   # Source date format, not renamed
    data_type: DATE
    nullable:
      MD: false
      MP: true            # MP feed sometimes omits this
  - name: plan_cd
    data_type: VARCHAR
    length: 10
    nullable:
      MD: true
      MP: true
```

A silver table that standardizes across sources would have its own UMF with
different column names, additional derived columns, and explicit provenance
columns tracking which source each row came from.
