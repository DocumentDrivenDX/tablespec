# Mixed legal pack 1.1.0

Generated consumer snapshot of UMF's `spec/domain-packs/legal`. Eight firm-operation
tables remain fabricated. Three observed tables preserve one public Google digital
advertising antitrust case, seven original PDFs and 383 PDF-page text records:
a complaint, judicial opinion, two deposition selections and three corporate
exhibits. Observed evidence is never scaled or associated with fictional clients.
Original PDFs are authoritative; text extraction is a lossy search aid without OCR.
Source URLs, byte hashes, Bates candidates and rights status are retained.
The ontology target covers only fabricated operations and remains a graph candidate.

Preflight all eleven tables without authentication or target writes:

```sh
tablespec sample-data ingest --mixed \
  --pack examples/domain-packs/legal/domain-pack.json \
  --source-policy local-use --scale small --seed 42 \
  --target YOUR_CATALOG.legal_mixed --dry-run
```

Use `scripts/load_mixed_legal_databricks.py` for runtime Spark loading and optional
original-PDF storage in a Unity Catalog Volume. See `docs/guide/sample-data.md`
for warehouse arguments, wheel installation, replacement semantics and verification.
Keep adjacent schemas, CSVs and PDFs with the manifest when uploading the pack.

`local-use` is an explicit processing choice and retains unknown third-party reuse
rights. It does not clear redistribution. The default policy and redistributable
ZIP export refuse unknown rights. The built-in legal generator and `examples/legal`
remain the all-fabricated compatibility surfaces.
