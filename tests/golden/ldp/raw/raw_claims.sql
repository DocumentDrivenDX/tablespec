CREATE OR REFRESH STREAMING TABLE raw_claims
COMMENT 'Raw landing for claims (continuous file ingestion).'
AS SELECT *
FROM STREAM read_files(
  '${landing_path}/claims',
  format => 'csv'
);