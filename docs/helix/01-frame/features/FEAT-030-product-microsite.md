---
ddx:
  id: FEAT-030
---

# Feature Specification: FEAT-030 — Product Microsite

**Feature ID**: FEAT-030
**Status**: Approved
**Priority**: P1
**Owner**: Platform / Developer Experience
**Covered PRD Subsystem(s)**: None — documentation/meta-feature.
**Covered PRD Requirements**: None — meta-feature anchored to the Product Vision and Principles per the traceability convention (principles.md §Tension Resolution, decided 2026-06-10).
**Cross-Subsystem Rationale**: The microsite documents, explains, and demonstrates product behavior across subsystems; it does not introduce runtime product behavior.

## Description

Build a public product microsite for tablespec using Hugo + Hextra under `website/`.
The site explains what tablespec is, why source-semantic ingested bronze matters,
how to start correctly, and where to find exact reference material. It must
coexist with the existing GitHub Pages package index at `/simple/`.

## Motivation

The repository has source documentation and a release workflow that publishes a
minimal package-index landing page, but it does not have a real product
microsite. Evaluators need a first page that states the category and value
clearly; first-time users need a guided path from install to compile; active
users need concepts and reference without reverse-engineering the HELIX corpus or
API pages.

MkDocs remains useful for API reference generation (FEAT-015), but it is not the
right shell for the product microsite or the reader-mode information architecture
needed here.

## Functional Areas

| Area | User question or job | Feature responsibility |
|------|----------------------|------------------------|
| Product home | "What is tablespec, and is it worth evaluating?" | First viewport names the product/category, source-semantic bronze value, proof, and first action |
| Getting started | "How do I try it correctly?" | Install from the project package index, create/load UMF, compile artifacts, and run a validation path |
| Concepts | "What boundary does tablespec own?" | Explain UMF, raw vs ingested vs silver, committed artifacts, validation, and target emitters |
| Reference | "Where is the exact behavior?" | Link or embed API docs, CLI reference, generated artifact layouts, and governing concepts |
| Demos | "Can I see the workflow?" | Publish terminal/demo assets for the happy path and Databricks-oriented bootstrap |
| Deployment | "Can docs and package install both keep working?" | Build one Pages artifact that serves the Hugo site at `/` and preserves `/simple/` |

## Requirements

### Functional Requirements

SITE-01. The microsite SHALL live under `website/` and use Hugo extended with the
Hextra theme imported as a Hugo Module; the theme is pinned by `website/go.mod`
and `website/go.sum`.

SITE-02. The homepage SHALL answer product, category, audience, value, and first
action in the first viewport. It SHALL describe tablespec as a UMF compiler that
defines a source-semantic ingested bronze contract.

SITE-03. The top-level information architecture SHALL serve four reader modes:
Evaluate, Start, Decide, and Operate. Navigation SHALL separate "why", "use",
concepts, reference, and examples/demos rather than flattening them into one
document tree.

SITE-04. The site SHALL include at minimum: Home, Getting Started, Core Concepts,
CLI Reference, API Reference entry point, and Demos.

SITE-05. API reference remains governed by FEAT-015. The microsite SHALL either
embed generated API reference under a stable subpath or link to it through a
documented build step decided in ADR-014; it SHALL NOT silently replace API
reference generation.

SITE-06. The GitHub Pages artifact SHALL preserve the package index at `/simple/`
and the package project index at `/simple/tablespec/`. A documentation deploy
MUST NOT remove or truncate package links for previously released versions.

SITE-07. The Pages workflow SHALL make its publication cadence explicit. If docs
publish from `main`, the workflow must rebuild or carry forward `/simple/` on
every docs deploy; if docs publish only on version tags, that release-only cadence
must be visible in the site and workflow.

SITE-08. The implementation SHALL adapt from `../helix` only as a source
reference. tablespec's build, CI, and site generation SHALL have no runtime or
build-time dependency on the sibling repository.

### Non-Functional Requirements

- **Preserve install channel**: `pip install --index-url https://documentdrivendx.github.io/tablespec/simple/ tablespec` remains valid after the microsite deploys.
- **Deterministic build**: Hugo, Go modules, Node dependencies, and Playwright are pinned so local and CI builds produce stable output.
- **Responsive navigation**: Desktop and mobile navigation expose the same core pages; page-local navigation remains subordinate to site hierarchy.
- **Minimal custom styling**: Prefer Hextra configuration and shortcodes; add custom CSS only for site goals the framework cannot express.

## User Stories

- [US-038 — Publish Product Microsite](../user-stories/US-038-publish-product-microsite.md)

## Edge Cases and Error Handling

- **Docs-only deploy with no release artifact**: the workflow must still preserve
  `/simple/` from release metadata or a carried-forward artifact; it must not
  publish an empty package index.
- **Historical release links**: `/simple/tablespec/` must include existing
  release files, not only the latest build.
- **API reference unavailable**: the microsite may ship without embedded generated
  API pages only if it has a clear API Reference entry point and a tracked
  follow-up; broken links fail the docs build.
- **Missing sibling repo**: `../helix` is optional reference material only; the
  build succeeds when the sibling directory is absent.

## Success Metrics

- A first-time evaluator can identify the product, audience, value, and first
  action from the homepage.
- `hugo --gc --minify` builds the site from `website/` in CI.
- Playwright verifies homepage, top-level section pages, representative deep
  pages, desktop/mobile screenshots, and navigation state.
- A Pages artifact inspection test proves `/index.html`, `/simple/index.html`,
  and `/simple/tablespec/index.html` all exist before deployment.
- Release verification still installs tablespec from the Pages package index.

## Dependencies

- **Feature Specs**: FEAT-015 (API reference generation).
- **ADR**: ADR-014 (Hugo/Hextra microsite and GitHub Pages package-index coexistence).
- **Concerns**: `hugo-hextra`, `product-microsite-ia`, `testing`, `verification`.
- **External tooling**: Hugo extended, Go modules, Node/npm, Playwright.

## Out of Scope

- A logged-in application, operational dashboard, or runtime web UI.
- Replacing the Python API reference generation contract owned by FEAT-015.
- Changing package publishing away from GitHub Releases and GitHub Pages unless a
  separate release ADR supersedes the current install channel.
- Deploying Databricks jobs or running production pipelines from the site.

## Review Checklist

- [x] Meta-feature status is explicit; no new runtime FR is claimed.
- [x] Existing `/simple/` package index preservation is a requirement, not an implementation afterthought.
- [x] API reference ownership remains with FEAT-015.
- [x] Hugo/Hextra and product-microsite IA concerns are named.
- [x] Browser/Playwright testing is part of the feature scope.
- [x] No build-time dependency on `../helix`.
