CREATE OR REFRESH MATERIALIZED VIEW ingested_dump_null_escape
(
  CONSTRAINT not_null_row_id EXPECT (row_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        row_id AS row_id,
        token  AS token
FROM raw_dump_null_escape;