# Domain-pack loader companion 1.0.0

Use this finite document loader to create a source corpus and refresh it from a
cron job. The court profile accepts selected PDFs; the SEC profile accepts
selected SEC document/API URLs. Both retain unchanged original bytes and publish
metadata rows with revision hashes. The distribution requires **Bun 1.3.14**.

## Install and select sources

Download a companion from the UMF GitHub Pages distribution:

- [Court documents](https://documentdrivendx.github.io/umf/loaders/court-documents-loader-demo.zip)
- [SEC filings](https://documentdrivendx.github.io/umf/loaders/sec-filings-loader-demo.zip)
- [Release inventory and checksums](https://documentdrivendx.github.io/umf/loaders/release.json)

Trust the published release before running downloaded code. A checksum proves
consistency, not authorship; arbitrary downloaded `run.ts` files are outside this
trust boundary. The repository's exporter independently matches companion bytes
to its installed canonical release and refuses replaced code even when a pack
updates its own checksums. The standalone runner then checks installation integrity.

Extract the ZIP into a directory you control. Copy `inventory.json` to an external
configuration directory and add explicit entries. Empty examples deliberately
contain no live records. Example entry (replace every source-specific value):

```json
{
  "id": "selected-court:case-and-document-id",
  "url": "https://selected-court.gov/path/opinion.pdf",
  "media_type": "application/pdf",
  "license": {"redistribution": "unknown"},
  "metadata": {"court": "selected court", "document_kind": "opinion"}
}
```

Add the exact hostname to `allowed_hosts`. URLs require HTTPS and cannot redirect,
contain credentials or use nonstandard ports. Declare rights per selected source:
restricted refuses; unknown permits explicit local-use only. Public accessibility
alone does not establish redistribution rights. Court orders, amended opinions,
filing accessions and exhibits need distinct attributable IDs where appropriate.
No timestamp watermark skips older selected entries: refresh rechecks every entry.

The SEC profile permits `www.sec.gov` and `data.sec.gov` only, requires at least
one second between serial requests, and needs an organization/contact user agent:

```sh
export UMF_LOADER_USER_AGENT='YourOrganization research contact@example.org'
```

Coordinate all workers sharing your SEC user identity externally. One runner's
rate control cannot establish compliance across machines. SEC Company Facts API
bytes are retained as JSON; this release does not project financial numeric facts.
Source guidance: [SEC developer resources](https://www.sec.gov/about/developer-resources).

## Run and schedule

Use absolute paths; the working directory does not matter. State must be a private
local directory on one filesystem, separate from the installed pack/configuration.
Example for the court bundle:

```sh
/absolute/path/to/bun /opt/packs/court-documents-loader-demo/run.ts \
  --pack /opt/packs/court-documents-loader-demo/domain-pack.json \
  --inventory /opt/config/court-inventory.json \
  --state /var/lib/umf/court \
  --mode backfill --rights local-use
```

For SEC, substitute its bundle, inventory and state paths and supply the user
agent in the invoking environment. No credentials are stored by the runner.
Subsequent runs use `--mode refresh`; a daily cron example is:

```cron
15 6 * * * /absolute/path/to/bun /opt/packs/court-documents-loader-demo/run.ts --pack /opt/packs/court-documents-loader-demo/domain-pack.json --inventory /opt/config/court-inventory.json --state /var/lib/umf/court --mode refresh --rights local-use >>/var/log/umf-court.log 2>&1
```

Cron's environment must provide any required user agent. Exit 0 means a complete
snapshot was committed; 1 means failed/refused; 2 means usage error. Empty success
reports scope `[]`. Collection failures identify failed IDs and leave the prior
snapshot current. Run log JSON and `runs/` receipts expose failures; missing final
receipts require operator investigation. A lock refuses overlapping invocations.

## Inspect, replay and recover

`current.json` contains a manifest path and its SHA-256 checksum. Resolve that
pointer to inspect the immutable publication's `documents.jsonl`, `manifest.json`,
`inventory.json`, `receipt.json` and `objects/<sha256>` originals. Only the pointer
marks a complete publication. Histories retain prior revisions and observations;
absence from a later inventory means unselected, never withdrawn or vacated.
Metadata changes and URL/rights changes survive even when bytes are unchanged.

Run `--mode replay` with the same pack, state and rights and omit `--inventory`.
Replay uses the committed inventory and verifies retained hashes and projection
without network requests. Supplying a different inventory refuses. It does not
reclassify PDFs or rerun a model; the projection is document metadata only.

Update the external inventory's entries to extend the dataset; keep its stable
`id`. A different inventory ID, pack manifest, profile, implementation or rights
selection needs a new state directory. Keep old state for provenance/recovery.
The published companion configuration and pack stay pinned while selections vary.

After a killed process, confirm no runner is active before removing `state/lock`,
then rerun. Do not steal a live lock. Orphan publications remain uncommitted and
may be retained for inspection. A committed receipt is prepared before atomic
pointer rename; post-commit cleanup warnings preserve exit success. Local process
interruption is covered; power-loss durability and network filesystems are unqualified.

Bounds apply to consumed response bytes including retries: 50 MiB per attempt,
500 MiB per run, at most 1000 selected documents and three retries. Inventory
configuration can choose tighter bounds. Entire requests, including streamed
bodies, time out. Budget refusal occurs at a received chunk boundary and prevents
all later requests after exhaustion; limits qualify consumed application chunks,
not physical wire traffic or the runtime's internal buffers. State snapshots refuse above 500 MiB unique original bytes,
10000 historical rows/config revisions, 100000 retrieval observations, or a
100 MiB manifest metadata cap. Preserve
old state and start a newly scoped corpus when limits are reached; no automatic
history deletion occurs. Host allowlisting assumes trusted DNS and is not a DNS
rebinding defense.

## Consumer boundary

The output is an original-document corpus with JSONL metadata. TableSpec owns
subsequent tabular ingestion; Truss/Ashlar own graph storage. Source-list discovery,
PDF parsing, financial-fact projection, split screening, attorney review, PACER,
model selection and email are separate stages. No database or cron job is installed
by downloading the pack. Court and SEC support claims cover finite inventories,
not full live coverage of those ecosystems.

## Feed a domain projection

Use the separately bundled `read-publication.ts` to select verified retained bytes
without changing acquisition state. Its selection file is a JSON array:

```json
[{"id":"selected-court:case-and-document-id"}]
```

Omitting `revision` selects that source's current row. Supplying a byte-hash
`revision` selects all retained contexts for that source/version, preserving URL,
metadata and rights distinctions. Selected byte copies are preflighted against
a 500 MiB aggregate cap, counting every returned context even when original
objects share a hash; narrow selections if the bridge refuses. Missing IDs/revisions and duplicate selections
refuse. The bridge verifies the whole committed closure, writes original bytes
under `objects/` and a provenance-bearing `selection.json` into a new directory:

```sh
/absolute/path/to/bun /opt/packs/court-documents-loader-demo/read-publication.ts   --state /var/lib/umf/court --selection /opt/config/selection.json   --output /opt/projections/new-corpus-input
```

The rights status survives this local processing handoff. It does not clear
redistribution or execute a projection. A trusted domain builder consumes selected
originals, applies bounded exact-token/concept/window filters, and authors its own
new corpus revision. Large SEC JSON remains bytes until that bounded adapter;
loading it wholesale into the browser's native JSON parser can exceed its limits.

An inventory entry may set `expected_sha256` to enforce exact historical bytes.
A mismatch fails collection and preserves the prior publication. The pin applies
in both backfill and refresh; omit it to admit legitimate changed revisions.
Checksums inside `metadata` are documentary annotations and never enforced pins.

This release's development snapshots changed during review. After public release,
1.0.0 canonical bytes are immutable: a changed runner or companion guide/schema
requires a new implementation version and release. For scheduled upgrades, retain
old installations/state, install the new exact bundle, create a new state bound to
its pack/runner hashes, qualify backfill/replay, then change the scheduler path.
No silent state migration, history deletion or scheduled source switch occurs.
