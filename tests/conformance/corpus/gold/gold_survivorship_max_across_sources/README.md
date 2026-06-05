# gold_survivorship_max_across_sources

GREATEST-based (`max_across_sources`) survivorship over `union_sources`, with a
`COALESCE(GREATEST(...), default_value)` fallback. See `cases.yaml` for the
generator path this case exercises. Source UMFs + CSVs are committed here; the
canonical golden is the Spark-backend output of the `SQLPlanGeneratorGold` tier,
executed on BOTH the Spark session and DuckDB.
