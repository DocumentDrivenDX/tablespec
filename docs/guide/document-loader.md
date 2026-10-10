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
