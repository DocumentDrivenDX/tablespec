# Onboarding authoring-reduction benchmark

PRD success metric: **at least 50% lower** transform/validation authoring time
per onboarded table vs hand-authored baseline, measured on a **3-table**
onboarding sample.

## Automated sample (tablespec path)

The in-repo sample is the Path B e2e fixture set:

| Table | Spec |
|-------|------|
| `member` | `tests/e2e/fixtures/member.umf.yaml` |
| `claims` | `tests/e2e/fixtures/claims.umf.yaml` |
| `claim_enriched` | `tests/e2e/fixtures/claim_enriched.umf.yaml` |

### Run

```bash
uv run python scripts/onboarding_benchmark.py --out /tmp/onboard-metrics
```

This records:

- wall time for `umfs_from_specs` + `compile_umfs` (and optionally backbone)
- per-table artifact presence (ingest SQL, DDL, suite, dbt ingest, …)
- gold DAG / LDP project presence

Output: `/tmp/onboard-metrics/onboarding_benchmark.json`.

Unit gate (no Spark required):

```bash
uv run pytest tests/unit/test_onboarding_benchmark.py -q
```

## Manual baseline protocol

To compute reduction, time a **manual** 3-table onboarding of the same
semantics (member, claims, claim_enriched) *without* tablespec compile:

1. Hand-write Spark DDL / dbt models / GX suite / LDP stubs for all three.
2. Record elapsed wall-clock minutes \(t_{manual}\).
3. Run the automated harness above; use `seconds.total_automated` as
   \(t_{tablespec}\).
4. Reduction = \(1 - t_{tablespec}/(t_{manual}\times 60)\).

The automated harness is the **reproducible numerator**. A sample automated
metrics file is committed at
[`docs/helix/06-iterate/metrics/onboarding_benchmark.json`](../helix/06-iterate/metrics/onboarding_benchmark.json)
(regenerate with the command above). The manual denominator is
operator-measured once per release and may be stored alongside that file as
`manual_baseline.json` if desired (optional; not agent-produced).

## Relation to the happy path

This sample is the same Path B composition as [happy-path.md](happy-path.md)
and `scripts/bootstrap_from_specs.py`, scoped for metric capture rather than
demo narration.
