---
ddx:
  id: brand-voice
  links:
    - type: informed_by
      target: product-vision
    - type: informed_by
      target: principles
    - type: informs
      target: design-system
    - type: informs
      target: FEAT-030
---

# Brand Voice

tablespec sounds like an engineering blueprint: exact, calm, inspectable, and
unimpressed by vague platform language. It explains contracts, boundaries, and
runtime artifacts in the terms data engineers already use.

The voice should make a reader think: this project knows where the boundary is,
what file changes, what command runs, and what downstream system consumes the
artifact.

## Audience

Write for intelligent technical readers who are new to tablespec. The primary
audience is data engineers, analytics engineers, platform engineers, and
technical data stewards who understand tables, schemas, validation, and data
pipelines, but may not know UMF, tablespec's artifact catalog, Databricks
Lakeflow, Great Expectations, or this project's bronze/silver boundary.

Do not assume the reader has followed previous pages. A page or module should
stand on its own by naming:

- who should read it
- what problem it addresses
- what each local term means
- which file, command, API, or artifact changes
- where to go for a deeper definition

Avoid definite-reference shortcuts such as `the reusable catalog`,
`the contract`, `the artifact`, or `the runtime surface` until the sentence has
named the catalog, contract, artifact, or surface. Use the full noun first:
`the reusable catalog of generated SQL, schema, validation, dbt, and Lakeflow
artifacts`.

## Positioning Sentence

tablespec defines the source-semantic ingested bronze contract and compiles one
UMF into the SQL, dbt, Lakeflow, schema, and validation artifacts a data
platform actually runs.

Use this as the default spine for homepage, docs, and demo copy. Shorten it
when needed, but do not replace it with generic data-platform language.

## Voice Principles

1. **Contract before aspiration.** Say what tablespec defines, emits, validates,
   or refuses. Do not lead with broad promises.
2. **Artifacts over abstractions.** Name the files and surfaces: UMF,
   `ingest.sql`, `schema.json`, GX suite, dbt project, Lakeflow pipeline.
3. **Boundaries over buzzwords.** Explain where raw ends, where ingested bronze
   is done, and where silver begins.
4. **Source semantics, not source accidents.** Preserve source meaning; reject
   avoidable quirks like flat-file string typing, ambiguous casts, and dump
   formatting as downstream contracts.
5. **Reviewability is the value.** A change should become a diff in committed
   artifacts, not a runtime surprise.
6. **Healthcare examples are concrete.** Use MD, MP, ME, claims, eligibility,
   members, providers, and source feeds when examples need a domain.
7. **No synthetic excitement.** Do not sound impressed by the product. State the
   boundary and the consequence.
8. **No process theater.** Product docs describe what to run and what success
   looks like. They do not instruct readers to file tracker tickets, attach
   screenshots for evidence, or treat demo runs as audit rituals.
9. **Honest delivery status.** Shipped work is shipped. Workspace walkthroughs
   are product docs (Getting Started), not "open residuals" or "bead leftovers."
   Reserve gap language for real missing implementation, not for "not in default CI."

## Tone

| Attribute | Rule |
|---|---|
| Precise | Use concrete nouns and verbs. Prefer `compiles`, `validates`, `emits`, `fails`, `preserves`, `records`. |
| Calm | No hype, no exclamation points, no inflated adjectives. |
| Technical | Use the platform terms directly: Spark, Databricks, Delta, Unity Catalog, dbt, Lakeflow, GX. |
| Skeptical | Treat drift, silent validation, and runtime schema derivation as hazards to control. |
| Source-faithful | Keep the distinction between source semantics and silver decisions explicit. |

## Approved Language

Use these phrases consistently:

- `source-semantic ingested bronze`
- `definition of done for ingested bronze`
- `committed runtime artifacts`
- `reviewable diffs`
- `one UMF`
- `raw to ingested`
- `typed, validated, keyed, relationship-aware`
- `source semantics`
- `source accidents`
- `compile once, run from artifacts`
- `Connect-safe validation`
- `fails closed`

## Avoided Language

Do not use these phrases in product or docs copy:

- `unlock your data potential`
- `seamlessly transform your data`
- `single pane of glass`
- `democratize data`
- `AI-powered` unless the specific feature is actually AI-powered
- `next-generation`
- `revolutionary`
- `effortless`
- `magic`
- `beautiful docs`
- `modern data stack` unless naming the actual tools

Also avoid vague nouns such as `solution`, `platform`, `workflow`, or
`experience` when a concrete noun is available.

### Process and tracker jargon (docs & microsite)

Do **not** use these in product-facing Getting Started, demos, FEAT status
banners, or user-story acceptance prose:

- `PASS tickets` / `file PASS evidence` / `attach screenshots to the tracker`
- `operational residual` / `bead residual` / `implementation residual` as a
  product status (say what is shipped and where the runbook lives)
- `not CI-gated` / `waived for CI` as the main status of a demo (say which
  notebooks or microsite page to run)
- `agent gates` / `agent-executable` in user-facing copy
- `Nothing here is required for default CI` as a page lede (put opt-in test
  facts next to the commands that need secrets, not as apology)

Internal HELIX alignment reviews and bead descriptions may use residual
language when recording a point-in-time gap analysis. That does not belong on
the public microsite or in "Delivery" banners for shipped features.

## Say This, Not That

| Instead of | Say |
|---|---|
| Unlock trusted data pipelines. | Compile one UMF into the artifacts your pipeline runs. |
| Seamlessly bridge raw and silver. | Define where ingested bronze is done and where silver work begins. |
| Modernize schema management. | Replace per-tool schema drift with committed artifacts generated from one UMF. |
| Data quality made easy. | Generate validation suites from the same contract that defines the table. |
| Source preserving bronze. | Source-semantic ingested bronze: typed, validated, keyed, and still faithful to the source. |
| Eliminate complexity. | Move type casting, validation, and artifact generation into a reviewed compile step. |
| Workspace job residual / not CI-gated. | Notebooks under `notebooks/…`; walkthrough on Getting Started → In a workspace. |
| Live deploy residual / open residual work. | Deploy steps: Getting Started → Deploy the app. Local smoke: `make app-smoke`. |
| File PASS evidence or attach screenshots. | *(Delete — success is the checkpoint table or command exit status.)* |
| Agent gates use the mock runtime. | Local smoke (no workspace): … |

## Headline Patterns

Good headlines use a product noun plus an engineering consequence.

- `Definition of done for ingested bronze`
- `One UMF. Every runtime artifact.`
- `Source semantics without source accidents`
- `Compile the contract. Review the diff.`
- `Raw stays auditable. Ingested becomes usable.`
- `Silver starts after the source contract is complete.`

Avoid headlines that could belong to any data product.

## Page-Level Rules

### Homepage

Lead with the bronze contract, not a general productivity promise. The homepage
must show the pipeline boundary and artifact outputs in the first two sections.

Required nouns near the top:

- `UMF`
- `ingested bronze`
- `runtime artifacts`
- `SQL`
- `dbt`
- `Lakeflow`
- `Great Expectations`

### Getting Started

Use imperative steps and exact commands. Keep explanatory text short and attach
it to the command or file it explains.

Good:

> Run `tablespec generate` after editing the UMF. The generated SQL and schema
> files are the review surface.

Weak:

> tablespec helps you get started with a simple workflow.

Workspace pages (In a workspace, Deploy the app):

- Lead with what the reader will do and what success looks like.
- Name notebooks, env vars, and checklists — not tracker policy.
- Put "default CI does not need a workspace" only next to opt-in test commands,
  never as the page thesis.

### Concepts

Every concept page should open with the boundary it defines. If a concept
changes what a user should do, name the command, file, or artifact affected.
Define local terms before using shorthand, and link to the deeper concept page
when a term belongs elsewhere.

### Demos

Demos should read like reproducible evidence, not a showcase. Name the source,
the generated artifacts, the validation result, and the environment.

## Sentence Shape

- Prefer 12-22 word sentences for public copy.
- Use one claim per sentence.
- Put the actor first when possible: `tablespec emits`, `the runtime consumes`,
  `the UMF records`.
- Use semicolons sparingly. If a sentence needs two semicolons, split it.
- Avoid parenthetical caveats in hero or CTA copy; move caveats to body text.

## Microcopy

Buttons:

- `Start with a UMF`
- `Read the bronze contract`
- `View compile artifacts`
- `Run the demo`
- `Open CLI reference`

Status chips:

- `compiled`
- `reviewable`
- `validated`
- `typed raw`
- `source-semantic`
- `fails closed`

Error and empty states:

- Name what failed.
- Name the file or command to inspect.
- Avoid blame and jokes.

## Feature and story status copy

When a FEAT or user story is **Built** for the library path:

- State what is shipped and where evidence lives (tests, examples, notebooks).
- Point workspace demos at microsite Getting Started or `notebooks/…/README.md`.
- Do not leave "Delivery" banners that still read as open residual work.

When something is truly unfinished:

- Name the missing behavior or file.
- Prefer a DDx bead over soft status language in public docs.

## Evolving this voice

This file is the single voice authority. Build on it in place:

1. **When a phrase fails twice** (reader confusion or repeated edit in review),
   add one row to **Avoided Language** or **Say This, Not That**.
2. **When shipping a public surface** (microsite page, CLI help, FEAT banner),
   run the checklist below.
3. **Do not** invent a second full voice doc. Root [`VOICE.md`](../../../VOICE.md)
   only points here.
4. Point-in-time alignment reviews may use residual jargon; **active** product
   copy must not inherit it unchanged.

## Voice Checklist

- [ ] Does the copy name the contract or artifact?
- [ ] Does it avoid generic platform claims?
- [ ] Does it preserve the raw / ingested bronze / silver boundary?
- [ ] Does it say what changes in review?
- [ ] Does it use one of the approved product terms when relevant?
- [ ] Does it avoid hype words and abstract value claims?
- [ ] Does it avoid process theater (PASS tickets, residual status, agent gates)?
- [ ] For workspace demos: does it name the runbook path instead of "not in CI"?
