CREATE OR REFRESH MATERIALIZED VIEW ingested_dump_footer_rows
(
  CONSTRAINT not_null_row_id EXPECT (row_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        row_id AS row_id,
        note   AS note
FROM raw_dump_footer_rows;