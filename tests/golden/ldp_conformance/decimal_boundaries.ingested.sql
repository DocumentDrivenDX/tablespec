CREATE OR REFRESH MATERIALIZED VIEW ingested_decimal_boundaries
(
  CONSTRAINT not_null_row_id EXPECT (row_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        row_id                                                                           AS row_id,
        cast(nullif(trim(regexp_replace(small_dec, '^\\$', '')), '') as DECIMAL(5,2))    AS small_dec,
        cast(nullif(trim(regexp_replace(big_int_dec, '^\\$', '')), '') as DECIMAL(38,0)) AS big_int_dec,
        cast(nullif(trim(regexp_replace(round_dec, '^\\$', '')), '') as DECIMAL(10,4))   AS round_dec
FROM raw_decimal_boundaries;