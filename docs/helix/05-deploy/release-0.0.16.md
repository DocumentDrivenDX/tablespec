---
ddx:
  id: tablespec.release.0.0.16
  type: release-notes
  activity: deploy
  authoring:
    home: repo
  links:
    - id: FEAT-033
      kind: informed_by
    - id: ADR-020
      kind: informed_by
---

# TableSpec 0.0.16

## Release Scope

Integrates PR #28's interactive guidebook and transitive column lineage with PR
#48's explicit serialized LDP job authority. Original contributor commits are
retained. Existing domain maps, glossary aliases, integration metadata and public
renderer entry points remain available.

## Audience and Channels

Python consumers and plugin users receive version 0.0.16 through the existing
GitHub, PyPI and Pages release pipeline.

## Highlights

The offline guidebook provides table and column tabs, source diagrams and
transitive lineage. Domain-map navigation and visible glossary definitions work
with the new payload-based renderer. LDP's fenced writer remains the default;
serialized authority requires explicit opt-in and validates freshness pins.

## Changes and Fixes

Integration reconciles domain-qualified foreign keys and Delta source locations.
201 focused guidebook, lineage, glossary, CLI and LDP cases pass locally. Strict
Pyright passes for guidebook, lineage and LDP. Chromium 148.0.7778.96 verifies
file-URL navigation, glossary alias text, a Synthea source diagram and mobile
rendering without page errors. Hosted checks separately qualify Linux delivery.

## Breaking Changes and Required Actions

Regenerate guidebooks to receive the interactive assets. Do not mix old generated
HTML with new assets. Serialized authority is an explicit trust/profile decision;
its opt-in does not establish concurrent-writer fencing.

## Migration or Rollback Guidance

Keep the source model and regenerate documentation with the selected package.
Existing native renderer entry points remain available. Reinstall 0.0.15 and
regenerate its output to roll back package-generated documentation.

## Known Issues and Support

This qualification does not extend Spark runtime, untested source adapters or
cross-system lineage semantics beyond their existing support records. Expression
lineage is constrained to the documented extraction subset.

## References

- [Interactive guidebook decision](../02-design/adr/ADR-020-interactive-guidebook-and-column-lineage.md)
- [Guidebook documentation](../../guide/guidebook.md)
