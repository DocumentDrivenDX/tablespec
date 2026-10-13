---
ddx:
  id: CONTRACT-002
  authoring:
    home: repo
  links:
    - id: prd
      kind: informed_by
    - id: architecture
      kind: informed_by
---

# CONTRACT-002: Native Python document loading and preservation

**Type:** CLI, protocol and sink boundary. **Version:** 1.0.0. **Status:** draft.

## Purpose

TableSpec owns native Python acquisition, offline transfer and publication of
UMF document packs. UMF owns inert pack declarations and schemas. Source bytes
remain authoritative independently of tabular metadata or derived text.

## Scope and Boundaries

Finite HTTPS inventories, original bytes, bounded immutable revision history,
BagIt transfer, preservation metadata and Spark/Delta or DuckDB metadata sinks
are in scope. Discovery, PDF parsing, financial projection, Snowflake execution,
OCFL archive storage and WARC capture are separate adapters, not implemented by
this contract. No Bun process is invoked. The installed canonical companion
1.0.0 is an independent admission authority for existing pack loader blocks;
its `runtime: bun` describes the retained compatibility runner.

## Normative Surface

| Surface | Required behavior |
| --- | --- |
| `fetch --pack --inventory --output --mode backfill\|refresh --rights` | Validate canonical five-file companion closure, inventory Draft 2020-12 schema, identities, HTTPS URLs, allowed hosts, media, rights and budgets before requests. `unknown` needs explicit `--rights local-use`; `restricted` always refuses. Default rights are `redistribute`. SEC needs identifying `UMF_LOADER_USER_AGENT` contact and >=1000 ms serial request starts. |
| Acquisition | No redirects, credentials or nonstandard ports. Enforce per-attempt wall time, retries, per-file/aggregate bytes including failed bodies, document count, expected SHA-256, media and PDF magic. Do not parse or reserialize original JSON. |
| State | `current.json` commits a hash-bound `publications/<uuid>/manifest.json`. Manifest 1.0.0 retains binding, committed inventory/hash, receipt/hash, metadata projection/hash, contexts, observations and inventory history. Originals live at `objects/<sha256>` and are never rewritten. Changed pack hash/version/profile/rights/stable inventory ID refuses existing state. |
| `replay` | Use the committed inventory and bytes without source requests. A differing supplied inventory refuses. |
| `handoff --state --output` | Export a complete [BagIt 1.0](https://www.rfc-editor.org/rfc/rfc8493.html) SHA-256 directory. Payload includes committed metadata, pack closure and all retained original revisions. Tags include `preservation.json`, `provenance.jsonld`, payload/tag manifests and Payload-Oxum. No fetch.txt or incomplete bag import. |
| `verify-handoff` | Verify bounded regular files, complete manifests, all hashes, payload count/bytes, canonical pack identity and preservation mapping before success. Reject symlinks, special files, traversal and extra/missing payloads. |
| `preservation.json` | `tablespec.preservation/1.0.0` semantic JSON mapping to [PREMIS Data Dictionary 3.0](https://www.loc.gov/standards/premis/v3/): file Objects with fixity/size, capture and fixity Events with timestamp/outcome/object/agent links, software Agent, and inventory Rights assertions. It MUST state this is not PREMIS XML. Rights MUST NOT infer legal clearance. |
| `provenance.jsonld` | [PROV-O](https://www.w3.org/TR/prov-o/) Entity, Activity and SoftwareAgent graph. Separate URL resource, observation-specific acquired copy and content-addressed original identities. Metadata projection uses exact original revisions. Domain extraction derivations require separately qualified source-revision bindings. |
| `audit --state` | Verify all retained original revisions and pack closure offline; return JSON receipt and nonzero on failure. Suitable for cron or a job scheduler. |
| `publish --fetched --backend --target --mode replace\|merge` | Verify entire state or BagIt before sink writes. Generate common metadata schema from admitted pack/profile. Publish original objects under caller-named directory/UC volume, SHA-keyed. Merge key is pack_id, pack_version, id, revision. Read back complete selected entry count, exact metadata rows and each original hash. Fail nonzero on any mismatch. |
| Targets | Spark accepts exactly catalog.schema.table and `/Volumes/<same catalog>/<same schema>/<volume>/<optional subpath>`. DuckDB accepts schema.table plus explicit database and object directory. No inferred fallback schemas or tables. Refuse incompatible schemas/constraints. Replace affects only the named table; merge preserves other revisions and packs. |
| `verify-release --release-json` | Compare an independently downloaded UMF release index to installed authority, without requiring outbound network. Record pack and loader contract versions separately from implementation agent version 0.0.8. |

## Precedence and Compatibility

Unknown annotations remain retained. Unsupported preservation profile values
refuse execution. Companion digests authorize only the installed contract;
network and write targets always come from explicit caller configuration.
BagIt hashes establish fixity, not authenticity. PREMIS JSON mapping is a
scoped profile, not full PREMIS serialization conformance. OCFL 1.1 and WARC
remain optional future adapters. Existing TS publication layout is not imported
as Python state; parity applies to original bytes and revision hashes.

## Error Semantics

Failures emit closed diagnostic codes and exit nonzero. Failed refresh leaves
the prior pointer authoritative. Temporary files may remain after process death;
original final paths are published only after complete writes. Kernel per-object
locks release on process death; filesystems without locking/atomic rename refuse
instead of weakening guarantees. The top-level state lock requires manual
recovery after confirming its process is dead. Sink read-back failure does not
promise cross-table/object-store rollback; retry the same explicit target.

## Examples

See [operator guide](../../../guide/document-loader.md) for fetch, BagIt,
DuckDB and in-process serverless publish commands and pinned dependencies.

## Non-Normative Notes

An archive can later implement [OCFL 1.1](https://ocfl.io/1.1.0/spec/) without
changing inventory acquisition. HTTP-context preservation can later implement
[WARC](https://www.loc.gov/preservation/digital/formats/fdd/fdd000236.shtml).
Neither feature follows merely from retaining content hashes.
