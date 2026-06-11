---
ddx:
  id: ADR-014
---

# ADR-014: Hugo/Hextra Product Microsite and GitHub Pages Package Index Coexistence

## Status

Accepted — governs FEAT-030 implementation.

## Context

tablespec currently has source documentation under `docs/` and a release workflow
that publishes GitHub Pages only on version tags. That Pages artifact is also the
package install channel: `/simple/` and `/simple/tablespec/` expose a PEP
503-style index whose links point at GitHub Release distribution files.

The project needs a real product microsite. The microsite must explain
tablespec's value, the source-semantic ingested bronze boundary, the happy path,
and exact reference surfaces. The existing MkDocs source can support API
reference generation, but it is not a deployed product microsite and should not
be treated as one.

The HELIX plugin provides `hugo-hextra` and `product-microsite-ia` concerns, and
the sibling `../helix` repository has a working Hugo/Hextra site that can inform
the implementation. tablespec cannot depend on that sibling repository at build
time.

## Decision

1. The product microsite uses Hugo extended + Hextra under `website/`.
2. Hextra is imported as a Hugo Module and pinned by `website/go.mod` /
   `website/go.sum`; no git submodule or copied theme is used.
3. `../helix` may be used as a source reference only. Any adapted structure,
   configuration, or content is copied into tablespec with attribution in the
   implementation commit; the build has no dependency on the sibling directory.
4. FEAT-015 continues to own API reference generation. FEAT-030 owns the product
   microsite shell, IA, demos, and Pages deployment. The microsite may embed API
   reference output under a stable subpath or link to a generated API reference
   entry point, but that integration must be explicit in the build.
5. GitHub Pages publishes one combined artifact containing the Hugo site at `/`
   and the package index at `/simple/`.
6. The package index is not generated only from the current release job's local
   `dist/` directory once docs can publish independently. A Pages deploy must
   rebuild `/simple/tablespec/` from release metadata, carry forward a previously
   published package index, or use an equivalent durable source so historical
   versions remain installable.
7. The publication cadence is explicit:
   - Version tags publish packages, refresh `/simple/`, build the microsite, and
     deploy the combined artifact.
   - A future main-branch docs workflow may publish documentation changes between
     releases only after it implements the same `/simple/` preservation rule.
8. A Pages artifact inspection test gates deployment by checking for at least
   `/index.html`, `/simple/index.html`, and `/simple/tablespec/index.html`.
9. Playwright covers homepage, top-level sections, representative deep pages,
   desktop/mobile screenshots, and navigation state.

## Consequences

- The install channel remains stable while the project gains a real public site.
- The release workflow cannot be naively replaced by a Hugo deploy that writes
  only the site root; doing so would break documented `pip install --index-url
  https://easel.github.io/tablespec/simple/ ...` commands.
- The first microsite implementation carries additional tooling: Hugo extended,
  Go modules, Node/npm, and Playwright.
- MkDocs is no longer the assumed public documentation shell. Its remaining role
  is API reference generation unless a later ADR replaces that mechanism.
- Browser/e2e testing becomes applicable to the microsite even though the
  tablespec product itself remains a library and compiler.

## Alternatives Considered

- **Keep the current Pages package-index landing page**: rejected because it does
  not answer evaluator, onboarding, concept, or reference questions.
- **Deploy Hugo on `main` and leave `/simple/` release-only**: rejected unless
  the docs workflow preserves or rebuilds `/simple/`; otherwise a docs deploy
  can erase the package index.
- **Replace MkDocs API generation immediately**: deferred. API reference strategy
  is a distinct integration point owned by FEAT-015.
- **Depend on `../helix` at build time**: rejected because the tablespec repo
  must build independently in CI and for contributors.

## Verification

- `hugo --gc --minify` from `website/`.
- `npm test` or `npm run test:e2e` from `website/` for Playwright.
- Pages artifact inspection proving `/index.html`, `/simple/index.html`, and
  `/simple/tablespec/index.html` exist before deploy.
- Release verification still installs tablespec from the Pages package index.

## Related

- FEAT-030 — Product Microsite.
- FEAT-015 — Browsable API Documentation.
- US-038 — Publish Product Microsite.
- `hugo-hextra` concern.
- `product-microsite-ia` concern.
