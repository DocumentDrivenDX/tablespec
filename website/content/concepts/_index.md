---
title: Core Concepts
weight: 2
next: /cli-reference
---

The concepts behind tablespec and Universal Metadata Format (UMF).

{{< cards >}}
  {{< card link="raw-ingested-silver" title="Raw, ingested, and silver" subtitle="The three-layer data boundary and what tablespec governs at each level." icon="database" >}}
  {{< card link="umf" title="Universal Metadata Format" subtitle="The split-format spec at the heart of tablespec — columns, types, per-context nullability, sources, and expectations." icon="academic-cap" >}}
  {{< card link="artifacts" title="Compiled artifacts" subtitle="SQL DDL, ingest SQL, PySpark and JSON schemas, GX suites, dbt projects, and Lakeflow pipelines — all derived from UMF." icon="cube-transparent" >}}
  {{< card link="validation" title="Validation model" subtitle="Staged raw/typed execution, severity and blocking, and Connect-safe verdicts on Databricks serverless." icon="beaker" >}}
{{< /cards >}}
