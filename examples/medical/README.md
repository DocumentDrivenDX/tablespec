# Official medical sample pack

This consumer snapshot comes from UMF's `spec/domain-packs/medical/pack.json`.
It contains 17 HL7 FHIR R4 illustrative resources projected into eight tables.
Original JSON, source hashes and licensing notices accompany the CSV fixtures.
CMS sources are references only; no CMS rows are included.

Import and export through the shared sample-data pipeline:

```sh
uv run tablespec sample-data ingest --pack examples/medical/domain-pack.json --output /tmp/medical.zip
uv run tablespec sample-data ingest --pack examples/medical/domain-pack.json --target samples.medical --dry-run
```

The loader validates pinned local sources, column types, unique keys and foreign
keys before producing the archive or loading. Select the existing Spark or
warehouse backend options for execution. ZIP `data/` contains normalized CSV;
`inputs/` preserves original sources and the manifest maps their references.

These official examples are synthetic illustrations, not clinical advice or a
representative longitudinal cohort. Clinical dates and decimal quantities remain
source literals; no conversions or inferred patient history are introduced.
See `licenses/NOTICE.txt` and source-level provenance for redistribution terms.

## LOINC notice

This material contains content from LOINC (http://loinc.org). LOINC is copyright
© Regenstrief Institute, Inc. and the Logical Observation Identifiers Names and
Codes (LOINC) Committee and is available at no cost under the license at
http://loinc.org/license. LOINC® is a registered United States trademark of
Regenstrief Institute, Inc.
