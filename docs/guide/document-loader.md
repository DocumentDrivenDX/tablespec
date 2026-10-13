# Document loading and preservation

TableSpec 0.0.9 provides native Python loading for UMF court and SEC document
packs. Originals stay byte-identical; metadata rows are a separate projection.
Bun, an additional HTTP client and a PDF library are not required.

```sh
tablespec document-loader fetch --pack pack.json --inventory inventory.json --output state --rights local-use
tablespec document-loader handoff --state state --output handoff
tablespec document-loader verify-handoff --fetched handoff
# Transfer the complete handoff directory to the isolated machine.
tablespec document-loader publish --fetched handoff --backend duckdb --target main.documents --database documents.duckdb --objects originals --mode merge
tablespec document-loader audit --state handoff
```

For refresh, use `fetch --mode refresh` with the same state, stable inventory ID
and pack installation. Identical bytes keep their revision hash and are never
rewritten. A changed pack manifest needs fresh state. A complete BagIt directory
contains originals, inventory, pack closure, metadata, PREMIS semantic JSON and
PROV-O JSON-LD; SHA-256 payload and tag manifests cover all of them.
`verify-handoff` accepts this complete bounded profile, not arbitrary BagIt bags.
PREMIS metadata maps Objects, Events, Agents and inventory Rights; it does not
claim PREMIS XML conformance or infer permission to redistribute. OCFL/WARC
adapters and PDF/text extraction are outside this release.

## Databricks serverless publishing

Stage the complete handoff at a caller-authorized path. Run publishing in the
notebook/job process using the runtime-provided Spark session:

```python
from pathlib import Path
from tablespec.document_loader import (
    validate_bag, validate_volume, LocalObjects, SparkMetadataSink, publish_sources,
)
from tablespec.spark_factory import create_delta_spark_session
state = validate_bag(Path('/Volumes/catalog/schema/transfers/handoff'))
target = 'catalog.schema.documents'
objects = LocalObjects(validate_volume(target, '/Volumes/catalog/schema/originals/collection'))
receipt = publish_sources(state, SparkMetadataSink(create_delta_spark_session("tablespec-document-loader"), target), objects, mode='merge')
```

Publication does not access GitHub, SEC or court hosts. The object filesystem
must support exclusive file locking and atomic rename; unsupported operations
refuse. Live Databricks serverless qualification is pending a caller-named
workspace/table/volume; local evidence must not be represented as a live runtime
check. Only the named table is replaced or merged. The volume must share its
catalog/schema. Publishing detects read-back failures but cannot atomically roll
back independent object and table stores; retry uses the same revision keys.

## Installation and pins

Install the released wheel with `--no-deps` in a prepared environment alongside
umf-core 0.8.1. Acquisition and BagIt use only the Python standard library plus
existing UMF serialization and JSON Schema validation. Explicit loader pins:
`jsonschema==4.25.1`, `umf-core==0.8.1`. DuckDB is optional: `duckdb==1.5.0`.
The TableSpec CLI additionally needs its existing declared requirements, including
`typer==0.24.1`, `click==8.3.1`, `rich==13.9.4`; use the released wheel metadata for
the complete base dependency set. Use the Databricks runtime's Spark rather than
installing a different PySpark in serverless. No new HTTP/PDF dependency is added.

SEC acquisition needs `UMF_LOADER_USER_AGENT` identifying the operator and a
contact email. Unknown redistribution rights require explicit `--rights local-use`;
restricted entries always refuse. Inventories are finite selections, not crawlers.
Download UMF's published `loaders/release.json` on the network-open machine and
pass `--release-json` or run `verify-release`; offline jobs use the independent
canonical closure packaged in the wheel.

Schedule `tablespec document-loader audit --state handoff` to check fixity.
Audit output is a JSON result with nonzero failure status; preserve the scheduler
run timestamp and output as operational evidence. Source bytes, acquired copies,
metadata projections and domain interpretation remain distinct identities.

## Court parity fixture

The documented fixture is
[`court-inventory.json`](https://github.com/DocumentDrivenDX/tablespec/blob/main/tests/fixtures/document-loader/court-inventory.json):
Loper Bright 22-451 and Trump 23-939 from supremecourt.gov, plus the DCD
1:20-cv-03010 opinion from govinfo.gov. All three entries retain unknown
redistribution rights and require explicit local-use. Live Python/Bun parity
checks produced identical original-byte revision hashes; no original PDFs are
redistributed in this TableSpec fixture.


## Published 0.0.9 artifacts

The [release](https://github.com/DocumentDrivenDX/tablespec/releases/tag/v0.0.9)
includes SHA256SUMS. Pin these published bytes:

```text
8258bf0c129dc872e9ba4bd5aedaadd1ea909b34cb4746cfc879acd931a08a0b  tablespec-0.0.9-py3-none-any.whl
6157b827c4e94175756bac918d78d3ddd27931454b763d6c4aaa8c9b7a006a8c  tablespec-0.0.9.tar.gz
```

The published wheel was installed with `--no-deps` alongside umf-core 0.8.1
in a prepared dependency environment. With outbound HTTPS blocked and Bun absent
from PATH, the court BagIt fixture published three rows and three original objects
to DuckDB and passed complete read-back. Live Databricks qualification remains pending.


## Local Spark qualification

The released TableSpec 0.0.9 and umf-core 0.8.1 wheels passed an independent
three-court-PDF driver probe on Python 3.12.15, Spark 4.0.1, Delta 4.0.0 and
Java 21.0.12.1. Checks cover exact acquisition hashes, unchanged refresh, offline
replay/BagIt/fixity, native Delta replace/read-back, repeated merge and wrong-schema
refusal preserving valid rows and original objects. Source HTTPS calls were
blocked in Python during publication; OS-wide network isolation was not tested.

[Evidence and discovery/qualification tools](https://documentdrivendx.github.io/umf/research/README.md)
are published separately from the wheel. The observed local probe retains
temporary paths and must not be run unchanged against remote targets. Live
Databricks serverless, Unity Catalog volume semantics and SEC acquisition remain
separate pending qualifications. No collector code changed for this evidence.
