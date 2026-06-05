# gold_unpivot_dedup

Sibling of `gold_unpivot`: exercises the `dedup_strategy == "latest"` branch of
`_generate_unpivot_base_view` (the base case exercises the no-dedup branch). The
wide source carries TWO snapshots per member (distinct `meta_load_dt`) and NO
primary_key, so the staging model blind-appends both; the gold model must keep
ALL quarter columns of the LATEST snapshot per member, then unpivot (EXCLUDE
NULLS). See cases.yaml for the generator path. Golden is the Spark-oracle output.
