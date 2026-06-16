---
title: tablespec
description: "tablespec helps data teams define the ingested bronze contract for source tables and compile one UMF spec into SQL, dbt, Lakeflow, schema, validation, Excel, and guidebook artifacts."
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
      tablespec is for data engineers and platform teams who need source data
      ready for downstream work. It defines a source-semantic ingested bronze
      contract: the source meaning is preserved, while types, validation,
      keys, and relationships are declared. Then it compiles one Universal
      Metadata Format (UMF) spec into SQL, dbt, Lakeflow, schema,
      validation, Excel review workbooks, and static guidebook artifacts.
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
        <small>records as delivered by another system</small>
      </div>
      <div class="ts-arrow" aria-hidden="true"></div>
      <div class="ts-node ts-node-raw">
        <span class="ts-node-label">raw</span>
        <strong>source records</strong>
        <small>transport shape kept for audit and replay</small>
      </div>
      <div class="ts-arrow" aria-hidden="true"></div>
      <div class="ts-node ts-node-ingested">
        <span class="ts-node-label">ingested bronze</span>
        <strong>typed, validated, keyed</strong>
        <small>source meaning captured in Delta-compatible tables</small>
      </div>
      <div class="ts-arrow" aria-hidden="true"></div>
      <div class="ts-node">
        <span class="ts-node-label">silver</span>
        <strong>conform, resolve, enrich</strong>
        <small>business choices across one or more sources</small>
      </div>
    </div>
    <div class="ts-artifact-strip" aria-label="Compiled artifacts">
      <div><span>UMF</span><code>tables/claims/table.yaml</code></div>
      <div><span>SQL</span><code>claims.ingest.sql</code></div>
      <div><span>dbt</span><code>models/claims.sql</code></div>
      <div><span>Lakeflow</span><code>pipeline.yml</code></div>
      <div><span>GX</span><code>suite.json</code></div>
      <div><span>Guidebook</span><code>index.html</code></div>
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
    <h2 id="ts-proof-title">One source-table spec, every generated artifact</h2>
  </div>
  <div class="ts-proof-grid">
    <article>
      <span>01</span>
      <h3>Define the source table once</h3>
      <p>Capture names, source types, nullability, keys, relationships, aliases, and provenance in Universal Metadata Format.</p>
    </article>
    <article>
      <span>02</span>
      <h3>Compile committed artifacts</h3>
      <p>Generate the SQL DDL, ingest transform, dbt model, Lakeflow pipeline, JSON Schema, Great Expectations suite, Excel workbook, and guidebook from that spec.</p>
    </article>
    <article>
      <span>03</span>
      <h3>Validate before silver starts</h3>
      <p>Run checks against raw source records and typed ingested tables before silver models add business rules.</p>
    </article>
  </div>
</section>

<section class="ts-band ts-example-preview" aria-labelledby="ts-example-title">
  <div class="ts-example-copy">
    <p class="ts-drawing-label">WORKED EXAMPLE</p>
    <h2 id="ts-example-title">Medical claims from UMF to reviewable artifacts</h2>
    <p>
      Start with a split-format UMF directory for `medical_claims`: one
      table-level YAML file plus one YAML file per column. tablespec validates
      that source-table contract, then emits raw-to-ingested SQL, a dbt project,
      a Great Expectations suite, and a guidebook from the same spec.
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
tablespec validation-sync tables/medical_claims --out gx/
tablespec guidebook tables/ -o site/guidebook</code></pre>
  </div>
</section>

<section class="ts-band" aria-labelledby="ts-boundary-title">
  <div class="ts-band-heading">
    <p class="ts-drawing-label">DECIDE</p>
    <h2 id="ts-boundary-title">Bronze records source meaning. Silver records business choices.</h2>
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
  <h2 id="ts-next-title">Compile the UMF contract. Review the diff.</h2>
  <p>Install tablespec, write one UMF source-table spec, generate runtime artifacts, then inspect the bronze boundary before silver work begins.</p>
  <div class="ts-hero-actions">
    <a class="ts-button ts-button-primary" href="getting-started/">Get started</a>
    <a class="ts-button ts-button-secondary" href="concepts/raw-ingested-silver/">Read raw, ingested, and silver</a>
  </div>
</section>
