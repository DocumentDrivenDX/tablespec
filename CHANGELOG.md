# Changelog

Releases are tagged `vX.Y.Z`; the package version comes from the tag. Release notes on GitHub are taken from this file.

## Unreleased

## 0.0.17 - 2026-11-11
- `umf-core` range widened to `>=0.10.0,<0.11` (was `<=0.10.3`); tested against umf-core 0.10.10.
- Native `columns-match-set` validation, ingest-cast knobs and counts-only results.
- `change_tracking` merge/rebuild strategies rendered for Spark, dbt and LDP; append sources; optional columns;
  ANSI-safe casts; strict plan references; Excel and external sources.
- pure-Python `umf-core==0.10.0` stays installable (Linux aarch64).
- CI reset: committed evidence, vendored tooling and process-only tests removed; one `ci.yml` with a fast/slow split; the README quickstart is now executed in CI.
- Release pipeline is now tag-driven with PyPI trusted publishing; GitHub Pages `/simple/` index retired (install from PyPI).

## 0.0.16 - 2026-11-02
- Release publication and PyPI propagation fixes.

## 0.0.15 - 2026-11-02
- Packaging and release workflow repairs.

## 0.0.14 - 2026-10-28
- umf-core 0.10 line; document-loader release notes.

## 0.0.13 - 2026-10-27
- Release workflow fixes (build output directory marker).

## 0.0.12 / 0.0.11 - 2026-10-20
- Document-pack and ingestion improvements.

## 0.0.10 - 2026-10-19
- UMF core split-format and domain updates.

## 0.0.9 - 2026-10-10
- Document acquisition and BagIt publication.

## 0.0.8 / 0.0.7 - 2026-10-09 and 2026-10-10
- Packaging and plugin manifest fixes.

## 0.0.6 .. 0.0.4 - 2026-10-08
- Release automation and documentation updates.

## 0.0.3 - 2026-09-01, 0.0.2 - 2026-07-10, 0.0.1 - 2025-10-06
- Early releases.
