# Fabricated legal sample

This minimal UMF example covers clients, matters, timekeepers, time entries,
invoices, documents, matter teams, and ethical walls. All content is fabricated;
no real people, firms, records, or credentials are used. Teams and walls enforce relational fixture consistency: unique pairs, disjoint
sets, a partner and another member per matter, and entries restricted to team
members. This is tabular test data; ontology work belongs in truss and ashlar.

From the repository root:

```bash
tablespec sample-data load --umf examples/legal/umf \
  --target sample_catalog.legal_demo --domain legal --scale small --dry-run
```

This command performs only local generation and verification. Use `--scale demo`
for 100,000 time entries or `--scale large` for three million. No workspace load
is needed to inspect DDL and counts. See `docs/guide/sample-data.md` for the
explicit warehouse-loading workflow, profile authentication, overrides,
constraint support, and per-table replacement semantics.


The eight presets retain their counts. `--skew-exponent 0.8` controls a truncated
power-law rank distribution, with coverage guaranteed for clients and matters.
Matter durations default to 30–1095 days; nullable close dates represent open
matters. Time entries include `hours`, `amount`, `block_billed`, and `vague_entry`.
Document bodies match their types; optional `nda_issues` labels seeded long-term,
residuals, and missing-law findings (about 8% of NDAs). UTBMS is an illustrative
litigation/transactional subset, not the full taxonomy.

Invoices have client, issue date, inclusive period bounds and exact period totals.
They are sample windows that can overlap, rather than a complete billing ledger.
Use `--bulk --volume /Volumes/catalog/schema/volume/path` explicitly for CSV upload
and COPY INTO through a warehouse. Normal loading reads back counts, FK integrity,
and entitlement checks. `--verify-only` reruns these checks without writing.
See the guide for requirements and failure behavior. Live loading is operator-run;
repository tests use offline SQL and Files API fakes.

The pack metadata and table schemas are owned by UMF under
`spec/domain-packs/legal/`. This directory is a generated consumer example.
Generate a verified, reproducible CSV archive without a workspace:

```bash
tablespec sample-data export --umf examples/legal/umf --domain legal \
  --domain-pack examples/legal/domain-pack.json --scale small --output legal-small.zip
```

The archive includes typed schema snapshots, source metadata and the generation
report. CSV uses explicit `\N` nulls and quoted empty strings. For ingestion,
`read_csv_rows` preserves those distinctions before a typed Delta write.
