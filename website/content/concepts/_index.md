---
title: Core Concepts
weight: 2
next: /cli-reference
---

These pages define the vocabulary used across tablespec. They are written for
technical readers who understand tables and pipelines but may be new to UMF,
ingested bronze, Great Expectations, dbt, or Databricks Lakeflow.

{{< cards >}}
  {{< card link="raw-ingested-silver" title="Raw, ingested, and silver" subtitle="Defines the data-layer boundary: raw records for audit, ingested bronze for source-table contracts, and silver for business decisions." icon="database" >}}
  {{< card link="umf" title="Universal Metadata Format" subtitle="Defines the UMF source-table spec: columns, types, per-context nullability, sources, relationships, and expectations." icon="academic-cap" >}}
  {{< card link="artifacts" title="Compiled artifacts" subtitle="Defines the reusable catalog of generated files: SQL DDL, ingest SQL, PySpark and JSON schemas, Great Expectations suites, dbt projects, and Lakeflow pipelines." icon="cube-transparent" >}}
  {{< card link="validation" title="Validation model" subtitle="Defines how generated Great Expectations suites run against raw records and typed ingested tables, including Databricks serverless behavior." icon="beaker" >}}
{{< /cards >}}
