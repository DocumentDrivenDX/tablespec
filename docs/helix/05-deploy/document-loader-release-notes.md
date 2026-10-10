---
ddx:
  id: tablespec.document-loader-release-notes
  authoring:
    home: repo
  links:
    - id: CONTRACT-002
      kind: informed_by
---

# TableSpec 0.0.8 — native document loading

## Release Scope

Native Python acquisition and offline publication for UMF court/SEC companion
contract 1.0.0. TableSpec owns the executable runtime. No Bun process or added
HTTP/PDF library is required. The release wheel and sdist are independently
checksum-pinnable; plugin manifests advance to 0.0.8.

## Audience and Channels

Document pack builders, cron/job operators and isolated Python data platforms.
GitHub release, Pages package index and product website carry the release.

## Highlights

Fetch selected originals, export complete BagIt 1.0 SHA-256 handoffs, publish
metadata/originals through DuckDB or explicit Spark/Unity Catalog targets, and
schedule offline fixity audits. PREMIS 3 semantic JSON and PROV-O JSON-LD
accompany originals. Refresh preserves unchanged revisions.

## Required Actions Summary

Use the [operator guide](../../guide/document-loader.md). Verify release asset
hashes and independently downloaded UMF loader release metadata. Unknown reuse
rights require explicit local-use; SEC requires identifying contact. Prepare
base dependencies before wheel installation with --no-deps.

## Changes and Fixes

Separate network-open fetch from isolated publish, validate canonical pack
closure before requests/writes, enforce serial requests and byte/time budgets,
and verify read-back. Stage immutable bytes before atomic publication; preserve
prior committed state on failed refresh. Refuse mismatched target constraints.

## Compatibility and Breaking Changes

Existing sample-data commands remain separate. Existing companion blocks are
admitted by their canonical1.0 closure; Python does not execute TS files.
Python state layout differs from TS state. Changing exact pack metadata requires
fresh state; original-byte parity does not imply state interchangeability.

## Migration or Rollback Guidance

Keep prior installations and states. Transfer the complete BagIt directory.
Retry failed publication on the same explicitly named target; independent object
and table stores do not provide a cross-store transaction. Top-level killed
state locks need operator recovery after proving no writer is active.

## Known Issues and Support

Live Spark/serverless and UC filesystem semantics remain unqualified without
a named workspace/table/volume. Live SEC fixture selection/contact is pending.
No Snowflake, PREMIS XML, OCFL repository or WARC capture claim is made.
Filesystems without required locking and atomic rename refuse. Supply pack,
loader, publication hashes and closed receipt codes for support.

## References

- [Contract](../02-design/contracts/CONTRACT-002-document-loader-preservation.md)
- [Execution evidence](../04-build/evidence/document-loader-preservation.md)
- [Release](https://github.com/DocumentDrivenDX/tablespec/releases/tag/v0.0.8)
