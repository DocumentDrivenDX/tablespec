# Fabricated legal sample

This minimal UMF example covers clients, matters, timekeepers, time entries,
invoices, documents, matter teams, and ethical walls. All content is fabricated;
no real people, firms, records, or credentials are used. Team/wall rows demonstrate
relationships, not a complete access-control or ethical-wall enforcement model.

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
