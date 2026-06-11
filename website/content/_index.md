---
title: tablespec
layout: hextra-home
---

{{< hextra/hero-badge link="concepts/raw-ingested-silver" >}}
  <span>Understand the boundary</span>
  {{< icon name="arrow-circle-right" attributes="height=14" >}}
{{< /hextra/hero-badge >}}

{{< hextra/hero-headline >}}
The UMF compiler for source-semantic&nbsp;bronze.
{{< /hextra/hero-headline >}}

{{< hextra/hero-subtitle >}}
tablespec defines the ingested bronze contract — the point where raw source
data becomes a schema-governed, source-faithful table your platform can build
on. It converts Universal Metadata Format (UMF) specs into SQL DDL, PySpark
schemas, Great Expectations suites, and validation reports.
{{< /hextra/hero-subtitle >}}

<div class="hx-mt-6 hx-mb-6">
{{< hextra/hero-button text="Get Started" link="getting-started" >}}
{{< hextra/hero-button text="Core Concepts" link="concepts" style="outline" >}}
</div>

<div class="hx-mt-12"></div>

## What tablespec does

tablespec sits at the ingestion boundary. You write a UMF schema that mirrors
your source — column names, types, nullability, and domain rules — and
tablespec compiles it into the artifacts your pipeline needs.

{{< cards >}}
  {{< card title="UMF Schema" subtitle="Author schemas in YAML with Pydantic validation. UMF is the single source of truth." icon="academic-cap" >}}
  {{< card title="Schema Generation" subtitle="Compile UMF into SQL DDL, PySpark schemas, and JSON Schema in one command." icon="code" >}}
  {{< card title="Validation" subtitle="Generate Great Expectations suites from UMF and validate DataFrames against the spec." icon="beaker" >}}
  {{< card title="Profiling" subtitle="Profile Spark DataFrames and reverse-engineer UMF specs from existing tables." icon="chart-bar" >}}
{{< /cards >}}

<div class="hx-mt-12"></div>

## Install

tablespec is distributed via GitHub Pages. Install it with uv or pip using the project package index at `easel.github.io/tablespec/simple/`. See [Getting Started](/getting-started/) for the full install path, Spark extras, and first compile walk-through.

<div class="hx-mt-12"></div>

## Why source-semantic bronze?

Most ingestion layers lose information at the boundary: they rename columns,
cast types, or apply conformance rules before the data is governed. That makes
it hard to trace a downstream anomaly back to the source feed.

tablespec enforces a different contract: **ingested bronze preserves source
semantics**. Column names match the source. Types match what the source
produces. Nullability reflects the source feed, not downstream assumptions.
That faithful snapshot is the foundation you govern everything else on.

Silver — cross-source conformance, survivorship, entity resolution, enrichment,
and dimensional modeling — belongs in a separate, explicitly governed layer.

{{< cards >}}
  {{< card link="concepts/raw-ingested-silver" title="Raw, ingested, and silver" subtitle="Understand the three-layer boundary that tablespec enforces." icon="database" >}}
  {{< card link="getting-started" title="Try the compile path" subtitle="Load a UMF spec and generate SQL DDL, PySpark schema, and GX baseline in minutes." icon="play" >}}
{{< /cards >}}
