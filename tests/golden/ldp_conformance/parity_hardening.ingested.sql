CREATE OR REFRESH MATERIALIZED VIEW ingested_parity_hardening
(
  CONSTRAINT not_null_row_id EXPECT (row_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        row_id                                                    AS row_id,
        cast(try_to_timestamp(padded_date, 'MM/dd/yyyy') as date) AS padded_date,
        cast(try_to_timestamp(compact_date, 'yyyyMMdd') as date)  AS compact_date,
        try_to_timestamp(micros_ts, 'yyyy-MM-dd HH:mm:ss.SSSSSS') AS micros_ts,
        try_to_timestamp(millis_ts, 'yyyy-MM-dd HH:mm:ss.SSS')    AS millis_ts
FROM raw_parity_hardening;