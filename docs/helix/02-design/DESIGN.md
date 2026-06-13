---
ddx:
  id: design-system
  links:
    - type: informed_by
      target: product-vision
    - type: informed_by
      target: principles
    - type: informs
      target: FEAT-030
---

# DESIGN.md - tablespec

This document governs the visual and interaction system for the tablespec
microsite and other public documentation surfaces. The direction is
**engineering blueprint**: precise, measured, inspectable, and built from the
same nouns the product uses. The site should feel like a reviewed platform
artifact, not a generic SaaS landing page.

The design expresses the product claim: one UMF compiles into committed,
reviewable runtime artifacts, and the ingested bronze layer has a concrete
definition of done.

## Navigation and Active State

The microsite uses a top navigation for the primary documentation areas and a
docs sidebar for section-local pages. Navigation should feel like a drawing
index on an engineering plan: visible structure, restrained labels, and exact
state.

**Active-state convention:** The active navigable destination MUST carry
`aria-current="page"` and a visible state derived from the same selector or
stable class. The visible cue is a 1px cyan rule plus increased text weight. On
sidebar items, the rule appears on the left edge; on top navigation items, it
appears under the label.

| Surface | Component | Active cue | Semantic |
|---|---|---|---|
| Primary nav | Top-level section links | 1px cyan underline, `font-weight: 650` | `aria-current="page"` |
| Section nav | Hextra/sidebar links | 1px cyan left rule, tinted background, `font-weight: 650` | `aria-current="page"` |
| In-page anchors | Table-of-contents links | 1px left rule and graphite text | `aria-current="true"` when supported |

Navigation labels should stay literal: `Getting Started`, `Concepts`,
`CLI Reference`, `API Reference`, `Demos`, `GitHub`. Do not invent campaign
labels like `Explore`, `Solutions`, or `Platform`.

## Visual Hierarchy

The page hierarchy follows a blueprint reading order: title block, system
diagram, artifact evidence, detail notes.

- **Layout**: Constrain prose to readable widths, but let diagrams and artifact
  strips span wider. Use fine dividing rules to separate bands instead of
  floating cards inside cards.
- **Hero**: First viewport must make `tablespec` and the bronze-contract promise
  visible. The supporting visual is a source-to-artifact blueprint diagram, not
  an abstract gradient.
- **Section structure**: Use full-width bands with ruled headers. Each major
  band should answer one question: what contract, what artifact, what boundary,
  what command.
- **Type scale**:
  - Display: 56px / 60px / 700 on desktop, 36px / 40px / 700 on mobile.
  - H1: 40px / 46px / 700.
  - H2: 28px / 34px / 700.
  - H3: 20px / 28px / 650.
  - Body: 16px / 26px / 400.
  - Technical caption: 12px / 18px / 500, uppercase labels only when they act
    like drawing annotations.
- **Weight and emphasis**: Use rules, labels, and code-like annotations before
  large type changes. Avoid oversized marketing copy below the hero.
- **Spacing rhythm**: Use 4px as the base unit. Most sections use 32px or 48px
  vertical spacing; dense artifact panels use 12px and 16px internal spacing.

## Interaction States

Interaction states are quiet but unambiguous. A keyboard user should always be
able to locate focus; a mouse user should see that controls are mechanical
parts of the blueprint.

| State | Applies to | Convention |
|---|---|---|
| Hover | Links, buttons, cards that navigate | Text shifts to graphite/ink; the rule or border shifts to cyan |
| `:focus-visible` | Links, buttons, tabs, inputs | 2px cyan outline, 2px offset, no outline removal |
| Active/current | Navigation links | Bound to `aria-current="page"`; see active-state convention |
| Disabled | Controls that cannot act | 40% opacity plus `disabled` or `aria-disabled`; never color alone |
| Loading | Build, search, generated-reference states | Inline progress label and stable reserved space |
| Empty | Missing examples, unavailable demos | Short reason, next concrete action, no decorative filler |
| Error | Failed build/demo/reference states | Plain-language failure and the command or file to inspect |

## Tokens

Tokens are concrete so the website CSS can implement this document directly.

### Color

The palette is graphite on cool drafting paper with cyan, green, amber, and red
used as annotation inks. Do not let the site collapse into a single blue/slate
theme.

| Token | Hex | Use |
|---|---:|---|
| `--ts-ink` | `#17191c` | Primary text, diagram labels |
| `--ts-graphite` | `#2f343a` | Headings, strong labels |
| `--ts-muted` | `#65707a` | Secondary prose |
| `--ts-paper` | `#f4f7f8` | Page background |
| `--ts-panel` | `#ffffff` | Artifact panels and code surfaces |
| `--ts-rule` | `#c8d2d8` | Fine rules and diagram grid lines |
| `--ts-cyan` | `#17a7b8` | Active rules, primary links, raw-to-ingested path |
| `--ts-green` | `#2f9f6a` | Passing checks, validated artifacts |
| `--ts-amber` | `#b7791f` | Warnings, boundary notes |
| `--ts-red` | `#b83b3b` | Errors and failed checks |
| `--ts-code` | `#101418` | Code block background |
| `--ts-code-ink` | `#e8edf0` | Code block text |

### Line, Radius, and Shadow

- Fine rules: `1px solid var(--ts-rule)`.
- Emphasis rules: `1px solid var(--ts-cyan)`.
- Cards and panels: 6px radius, never above 8px.
- Buttons: 4px radius.
- Shadows: avoid soft marketing shadows. Use either no shadow or
  `0 1px 0 rgba(23, 25, 28, 0.08)`.
- Diagrams: use 1px strokes and measured labels; no decorative orbs, bokeh, or
  abstract blobs.

### Spacing

Use this scale: `4, 8, 12, 16, 24, 32, 48, 64, 96`.

- Page bands: 64px desktop, 48px tablet, 32px mobile.
- Artifact panels: 16px padding, 12px gap.
- Navigation: 8px vertical padding, 16px horizontal padding.
- Diagrams: 24px minimum gap between labeled nodes on desktop; stack on mobile.

### Type

- Primary family: `IBM Plex Sans`, with a standards-compliant fallback stack.
- Mono family: `IBM Plex Mono`, then `ui-monospace`, then platform monospace.
- Avoid generic site-wide choices such as Arial, Roboto, Inter, or a bare system
  stack as the only brand expression.
- Letter spacing is `0` for normal prose. Use `0.06em` only for short technical
  labels, not paragraphs or buttons.

## Component Patterns

### Blueprint Hero

The hero presents the product as a system drawing:

- Title: `tablespec`
- Primary promise: `Definition of done for ingested bronze`
- Supporting line: one UMF compiles to SQL, dbt, Lakeflow, schemas, and GX.
- Visual: ruled pipeline from `source` to `raw` to `ingested bronze` to
  `silver`, with the tablespec contract drawn around the ingested boundary.
- CTAs: `Start with a UMF` and `Read the bronze contract`.

### Artifact Strip

An artifact strip shows the compiler output as evidence:

- `UMF`
- `ingest.sql`
- `schema.json`
- `suite.json`
- `dbt model`
- `Lakeflow`

Each artifact panel uses a short label, a 3-6 line excerpt, and a status chip
such as `compiled`, `validated`, or `reviewable`. The panels must not be
decorative only; they should contain real tablespec-shaped text.

### Layer Boundary Diagram

Use this component on the home page and `Raw, ingested, and silver` concept
page. It distinguishes:

- `raw`: source bytes/records for audit and replay.
- `ingested bronze`: source semantics captured in typed, validated,
  relationship-aware Delta-compatible artifacts.
- `silver`: conformance, survivorship, entity resolution, enrichment, and
  dimensional modeling.

The diagram should show that tablespec preserves source semantics without
preserving avoidable source accidents.

### Contract Checklist

Use a checklist component for the ingested bronze definition of done:

- Source captured by a declared `source.kind`.
- Types declared.
- Validation criteria generated.
- Keys and relationships defined.
- Aliases and provenance recorded.
- Ingested artifacts written and reviewable.

### Comparison Table

Use compact comparison tables for boundaries:

| Question | Ingested bronze | Silver |
|---|---|---|
| Renames columns? | No, preserve source names | Yes, when conformance requires it |
| Resolves duplicates across sources? | No | Yes |
| Captures source types? | Yes | Consumes them |
| Defines business survivorship? | No | Yes |

## Brand Voice Relationship

Visuals and copy must agree. The visual system uses fine rules, labels, and
artifact evidence; the voice uses concrete nouns, short claims, and direct
engineering consequences. Do not pair this visual system with vague product
copy.

The brand voice rules live in `docs/helix/01-frame/brand-voice.md`.

## Non-Goals

This document does not define:

- Runtime architecture, deployment, or package publishing.
- Data flow or ingestion semantics beyond their visual representation.
- Component implementation internals, Hugo shortcodes, or CSS file layout.
- ADR decisions about source contracts, emitters, validation, or runtime
  behavior.
- Full marketing strategy, pricing, or audience segmentation.

Those belong in architecture, ADRs, feature specs, or product artifacts.

## Review Checklist

- [x] Navigation section names the active-state convention and requires
      `aria-current="page"` on active nav items.
- [x] Active visual cues are bound to state.
- [x] Interaction states are scoped where applicable.
- [x] Visual hierarchy is concrete enough to implement.
- [x] Tokens name real values for color, spacing, line, radius, and type.
- [x] Non-goals keep architecture, data flow, component internals, and ADR
      material out of this document.
- [x] The direction reads as tablespec's interface system, not a generic design
      guideline.
