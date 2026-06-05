CREATE OR REFRESH MATERIALIZED VIEW ingested_tz_subsecond_timestamps
(
  CONSTRAINT not_null_row_id EXPECT (row_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        row_id                                                    AS row_id,
        try_to_timestamp(micros_ts, 'yyyy-MM-dd HH:mm:ss.SSSSSS') AS micros_ts,
        try_to_timestamp(millis_ts, 'yyyy-MM-dd HH:mm:ss.SSS')    AS millis_ts,
        try_to_timestamp(whole_ts, 'yyyy-MM-dd HH:mm:ss')         AS whole_ts
FROM raw_tz_subsecond_timestamps;