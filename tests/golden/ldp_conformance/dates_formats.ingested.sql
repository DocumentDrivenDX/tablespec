CREATE OR REFRESH MATERIALIZED VIEW ingested_dates_formats
(
  CONSTRAINT not_null_event_id EXPECT (event_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        event_id                                                 AS event_id,
        cast(try_to_timestamp(compact_date, 'yyyyMMdd') as date) AS compact_date,
        cast(try_to_timestamp(us_date, 'MM/dd/yyyy') as date)    AS us_date,
        try_to_timestamp(us_datetime, 'MM/dd/yyyy HH:mm:ss')     AS us_datetime,
        cast(try_to_timestamp(iso_date_noformat) as date)        AS iso_date_noformat,
        try_to_timestamp(iso_ts_noformat)                        AS iso_ts_noformat
FROM raw_dates_formats;