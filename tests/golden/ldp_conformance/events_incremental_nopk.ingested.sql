CREATE OR REFRESH STREAMING TABLE ingested_events
AS SELECT
        event_type                                                                  AS event_type,
        payload                                                                     AS payload,
        try_to_timestamp(occurred_at, 'yyyy-MM-dd HH:mm:ss')                        AS occurred_at,
        cast(nullif(trim(regexp_replace(amount, '^\\$', '')), '') as DECIMAL(10,2)) AS amount
FROM STREAM raw_events;