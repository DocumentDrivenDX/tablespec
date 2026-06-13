---
title: tablespec
description: "tablespec defines the source-semantic ingested bronze contract and compiles one UMF into SQL, dbt, Lakeflow, schema, and validation artifacts."
layout: hextra-home
---

<section class="ts-blueprint-hero" aria-labelledby="ts-home-title">
  <div class="ts-hero-copy">
    <a class="ts-hero-kicker" href="concepts/raw-ingested-silver/">
      Where bronze ends and silver begins
    </a>
    <p class="ts-drawing-label">TABLESPEC / SOURCE CONTRACT</p>
    <h1 id="ts-home-title">Definition of done for ingested bronze</h1>
    <p class="ts-hero-lede">
      tablespec defines the source-semantic ingested bronze contract and
      compiles one UMF into the SQL, dbt, Lakeflow, schema, and validation
      artifacts your platform actually runs.
    </p>
    <div class="ts-hero-actions" aria-label="Primary actions">
      <a class="ts-button ts-button-primary" href="getting-started/">Start with a UMF</a>
      <a class="ts-button ts-button-secondary" href="worked-example/">View the worked example</a>
    </div>
  </div>

  <div class="ts-blueprint-panel" aria-label="Raw to ingested bronze blueprint">
    <div class="ts-panel-title">
      <span>compile path</span>
      <span>review surface</span>
    </div>
    <div class="ts-pipeline">
      <div class="ts-node">
        <span class="ts-node-label">source</span>
        <strong>flat files, dumps, APIs</strong>
        <small>captured for audit and replay</small>
      </div>
      <div class="ts-arrow" aria-hidden="true"></div>
      <div class="ts-node ts-node-raw">
        <span class="ts-node-label">raw</span>
        <strong>source records</strong>
        <small>transport shape stays inspectable</small>
      </div>
      <div class="ts-arrow" aria-hidden="true"></div>
      <div class="ts-node ts-node-ingested">
        <span class="ts-node-label">ingested bronze</span>
        <strong>typed, validated, keyed</strong>
        <small>source semantics without source accidents</small>
      </div>
      <div class="ts-arrow" aria-hidden="true"></div>
      <div class="ts-node">
        <span class="ts-node-label">silver</span>
        <strong>conform, resolve, enrich</strong>
        <small>survivorship, enrichment, modeling</small>
      </div>
    </div>
    <div class="ts-artifact-strip" aria-label="Compiled artifacts">
      <div><span>UMF</span><code>tables/claims/table.yaml</code></div>
      <div><span>SQL</span><code>claims.ingest.sql</code></div>
      <div><span>dbt</span><code>models/claims.sql</code></div>
      <div><span>Lakeflow</span><code>pipeline.yml</code></div>
      <div><span>GX</span><code>suite.json</code></div>
    </div>
    <div class="ts-contract-row" aria-label="Ingested bronze contract checklist">
      <span>types declared</span>
      <span>validation generated</span>
      <span>keys recorded</span>
      <span>relationships defined</span>
      <span>artifacts committed</span>
    </div>
  </div>
</section>

<section class="ts-band ts-proof-band" aria-labelledby="ts-proof-title">
  <div class="ts-band-heading">
    <p class="ts-drawing-label">EVALUATE</p>
    <h2 id="ts-proof-title">One contract, every runtime surface</h2>
  </div>
  <div class="ts-proof-grid">
    <article>
      <span>01</span>
      <h3>Define the source table once</h3>
      <p>Capture names, source types, nullability, keys, relationships, aliases, and provenance in UMF.</p>
    </article>
    <article>
      <span>02</span>
      <h3>Compile committed artifacts</h3>
      <p>Generate SQL DDL, ingest transforms, dbt models, Lakeflow pipelines, JSON Schema, and GX suites.</p>
    </article>
    <article>
      <span>03</span>
      <h3>Validate before silver starts</h3>
      <p>Run staged raw and ingested checks with correct verdicts on classic Spark and Databricks serverless.</p>
    </article>
  </div>
</section>

<section class="ts-band ts-example-preview" aria-labelledby="ts-example-title">
  <div class="ts-example-copy">
    <p class="ts-drawing-label">WORKED EXAMPLE</p>
    <h2 id="ts-example-title">Medical claims from UMF to reviewable artifacts</h2>
    <p>
      Start with a split-format UMF for `medical_claims`. tablespec validates the
      contract, then emits the raw-to-ingested SQL, a dbt project, and a Great
      Expectations suite from the same source.
    </p>
    <a class="ts-button ts-button-secondary" href="worked-example/">Open the example</a>
  </div>
  <div class="ts-code-window" aria-label="Example compile command">
    <div class="ts-code-title">
      <span>terminal</span>
      <span>deterministic output</span>
    </div>
    <pre><code>tablespec validate tables/
tablespec generate tables/medical_claims -f ingest &gt; claims.ingest.sql
tablespec emit tables/ out/dbt --backend dbt --dialect databricks
tablespec validation-sync tables/medical_claims --out gx/</code></pre>
  </div>
</section>

<section class="ts-band" aria-labelledby="ts-boundary-title">
  <div class="ts-band-heading">
    <p class="ts-drawing-label">DECIDE</p>
    <h2 id="ts-boundary-title">Bronze stays source-semantic. Silver stays honest.</h2>
  </div>
  <div class="ts-comparison" role="table" aria-label="Ingested bronze and silver responsibilities">
    <div role="row" class="ts-comparison-head">
      <span role="columnheader">Question</span>
      <span role="columnheader">Ingested bronze</span>
      <span role="columnheader">Silver</span>
    </div>
    <div role="row">
      <span role="cell" data-label="Question">Renames columns?</span>
      <span role="cell" data-label="Ingested bronze">No. Preserve source names.</span>
      <span role="cell" data-label="Silver">Yes, when conformance requires it.</span>
    </div>
    <div role="row">
      <span role="cell" data-label="Question">Resolves duplicates across sources?</span>
      <span role="cell" data-label="Ingested bronze">No.</span>
      <span role="cell" data-label="Silver">Yes.</span>
    </div>
    <div role="row">
      <span role="cell" data-label="Question">Defines business survivorship?</span>
      <span role="cell" data-label="Ingested bronze">No.</span>
      <span role="cell" data-label="Silver">Yes.</span>
    </div>
    <div role="row">
      <span role="cell" data-label="Question">Feeds downstream systems?</span>
      <span role="cell" data-label="Ingested bronze">Yes. Typed, validated, keyed Delta-compatible artifacts.</span>
      <span role="cell" data-label="Silver">Consumes bronze and applies governed business decisions.</span>
    </div>
  </div>
</section>

<section class="ts-band ts-final-cta" aria-labelledby="ts-next-title">
  <p class="ts-drawing-label">OPERATE</p>
  <h2 id="ts-next-title">Compile the contract. Review the diff.</h2>
  <p>Install from the project package index, generate your first artifacts, then inspect the contract boundary before silver work begins.</p>
  <div class="ts-hero-actions">
    <a class="ts-button ts-button-primary" href="getting-started/">Get started</a>
    <a class="ts-button ts-button-secondary" href="concepts/raw-ingested-silver/">Read raw, ingested, and silver</a>
  </div>
</section>
