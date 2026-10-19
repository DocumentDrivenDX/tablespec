-- SPDX-License-Identifier: MIT OR Apache-2.0
CREATE OR REFRESH STREAMING TABLE raw_member
COMMENT 'Raw landing for member (continuous file ingestion).'
AS SELECT *
FROM STREAM read_files(
  '${landing_path}/member',
  format => 'csv'
);