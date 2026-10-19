-- SPDX-License-Identifier: MIT OR Apache-2.0
CREATE OR REFRESH STREAMING TABLE raw_events
COMMENT 'Raw landing for events (continuous file ingestion).'
AS SELECT *
FROM STREAM read_files(
  '${landing_path}/events',
  format => 'csv'
);