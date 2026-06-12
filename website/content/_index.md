---
title: tablespec
layout: hextra-home
---

{{< hextra/hero-badge link="concepts/raw-ingested-silver" >}}
  <span>Where bronze ends and silver begins</span>
  {{< icon name="arrow-circle-right" attributes="height=14" >}}
{{< /hextra/hero-badge >}}

{{< hextra/hero-headline >}}
Define the table once.&nbsp;Compile everything&nbsp;else.
{{< /hextra/hero-headline >}}

{{< hextra/hero-subtitle >}}
tablespec turns one YAML spec per table into every artifact your pipeline
needs — SQL DDL, ingest transforms, dbt projects, Lakeflow pipelines, and
Great Expectations suites. A schema change becomes one reviewable diff
instead of five tools quietly drifting apart. Runs on classic Spark and
Databricks serverless.
{{< /hextra/hero-subtitle >}}

<div class="hx-mt-6 hx-mb-6">
{{< hextra/hero-button text="Get Started" link="getting-started" >}}
{{< hextra/hero-button text="Core Concepts" link="concepts" style="outline" >}}
</div>

<div class="hx-mt-12"></div>

## What tablespec does

You describe each table in a Universal Metadata Format (UMF) spec — column
names, types, nullability, keys, relationships, and quality rules — and
tablespec compiles it, deterministically, into the artifacts your platform
actually runs. Recompiling an unchanged spec produces byte-identical output,
so drift between your schema and your pipeline is structurally impossible.

Already have the data? Point tablespec at existing Spark tables or a live
database and it writes the specs for you.

{{< cards >}}
  {{< card title="One spec per table" subtitle="A YAML file, validated by Pydantic, holding structure, keys, relationships, and quality rules — the single source of truth." icon="academic-cap" >}}
  {{< card title="Compile to everything" subtitle="SQL DDL, raw→ingest transforms, dbt projects, Lakeflow pipelines, PySpark and JSON schemas — all from one command, all diffable." icon="code" >}}
  {{< card title="Validate anywhere" subtitle="Great Expectations suites generated from the spec, with correct verdicts on classic Spark and Databricks serverless alike." icon="beaker" >}}
  {{< card title="Start from your data" subtitle="Profile Spark tables or discover a whole database over JDBC — one validated spec per table, no hand-typing." icon="chart-bar" >}}
{{< /cards >}}

<div class="hx-mt-12"></div>

## Install

tablespec is distributed via GitHub Pages. Install it with uv or pip using the project package index at `documentdrivendx.github.io/tablespec/simple/`. See [Getting Started](/getting-started/) for the full install path, Spark extras, and first compile walk-through.

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
