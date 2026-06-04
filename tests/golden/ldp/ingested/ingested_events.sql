CREATE OR REFRESH STREAMING TABLE ingested_events
(
  CONSTRAINT accepted_values_severity EXPECT (severity IS NULL OR severity IN ('LOW', 'HIGH')) ON VIOLATION DROP ROW
)
AS SELECT
        event_type                                                                  AS event_type,
        severity                                                                    AS severity,
        cast(nullif(trim(regexp_replace(amount, '^\\$', '')), '') as DECIMAL(10,2)) AS amount
FROM STREAM raw_events;