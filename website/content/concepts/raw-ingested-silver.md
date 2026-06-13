---
title: Raw, ingested, and silver
weight: 1
---

This page is for readers who know data pipelines but do not yet know
tablespec's layer vocabulary. It defines three terms used throughout the
project: raw source records, ingested bronze tables, and silver models.

tablespec governs the boundary between raw source data and ingested bronze.
Silver begins after the source-table contract is complete.

## The three layers

### Raw

Raw is data as it arrives from another system: files, API payloads, CDC
streams, or database exports. Raw has no tablespec contract. Column names are
whatever the source produces, types are whatever the transport format carries,
and nullability is unverified.

Raw is the ground truth for auditing and replay. It is not the foundation you
build business logic on.

### Ingested bronze

Ingested bronze is where tablespec operates. An ingested bronze table is still
source-faithful, but it is no longer an unchecked transport record. The
ingested bronze layer:

- **Preserves source semantics.** Column names match the source field names.
  Types reflect what the source system produces, not a downstream preference.
  Nullability is declared from the source feed's behavior.
- **Is governed by a UMF spec.** Universal Metadata Format (UMF) is the
  tablespec source-table contract. Every column has a declared type and
  per-context nullability. In healthcare feeds, common context labels are MD
  (Medicaid), MP (Medicare Part D), and ME (Medicare).
- **Is validated on load.** Great Expectations suites generated from the UMF
  verify each load before data flows to downstream models.

The ingested layer is the stable foundation. If something is wrong with the
data, you can trace it back to the source semantics preserved here rather than
guessing whether the problem was introduced by a conformance transform.

### Silver

Silver is where cross-source work begins. A silver model applies
transformations that require judgment beyond what the source system records:

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
is not source-faithful. It represents a business decision.

## Why the boundary matters

Most ingestion pipelines blur the boundary between ingested and silver.
Column renaming, type casting, and null-coalescing happen in the same job that
reads from the source. When something downstream breaks, it is hard to tell
whether the problem is in the source data or in a transform applied at
ingestion.

tablespec enforces the separation. The ingested bronze table mirrors the
source meaning: no renames, no type promotions, no nullability assumptions
beyond what the source feed exhibits. Silver transformations are separate jobs
with their own contracts.

The raw/ingested split is also how validation executes. String-shape checks
(castability, lengths, date formats) run against the raw landing table;
value and relationship checks run against the typed ingested table — and
sources that arrive already typed, like JDBC or Parquet, skip the raw string
checks entirely. See the [validation model](/concepts/validation/) for the
staged execution details.

## In practice

A UMF spec for an ingested bronze table keeps the source's own column names.
In split format, `tables/member_eligibility/table.yaml`:

```yaml
table_name: member_eligibility
canonical_name: Member Eligibility
description: Member eligibility - source-faithful ingested bronze from claims feed
version: '1.0'
```

and one file per column under `columns/`, each preserving the source name
and the feed's actual nullability:

```yaml
# columns/mbr_id.yaml -- source column name, not a standardized version
column:
  name: mbr_id
  data_type: VARCHAR
  length: 20
  nullable:
    MD: false
    MP: false
```

```yaml
# columns/elig_start_dt.yaml
column:
  name: elig_start_dt
  data_type: DATE
  nullable:
    MD: false
    MP: true    # the Medicare Part D feed sometimes omits this
```

A silver table that standardizes across sources would have its own UMF spec
with different column names, additional derived columns, and explicit
provenance columns tracking which source each row came from.
