---
title: Core Concepts
weight: 2
next: /cli-reference
---

The concepts behind tablespec and Universal Metadata Format (UMF).

{{< cards >}}
  {{< card link="raw-ingested-silver" title="Raw, ingested, and silver" subtitle="The three-layer data boundary and what tablespec governs at each level." icon="database" >}}
  {{< card link="umf" title="Universal Metadata Format" subtitle="The YAML schema format at the heart of tablespec — columns, types, nullability, and validation rules." icon="academic-cap" >}}
  {{< card link="artifacts" title="Compiled artifacts" subtitle="SQL DDL, PySpark schemas, Great Expectations suites, and JSON Schema — all derived from UMF." icon="cube-transparent" >}}
  {{< card link="validation" title="Validation model" subtitle="How tablespec generates and applies Great Expectations suites against DataFrames." icon="beaker" >}}
{{< /cards >}}
