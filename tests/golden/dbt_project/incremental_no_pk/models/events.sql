{{
    config(
        materialized='incremental',
    )
}}

-- WARNING: no primary_key + incremental -> blind append (no dedup).
-- Contract: raw source holds ONE batch per run; duplicates accumulate
-- on re-ingest of the same rows (matches the Spark INSERT INTO branch).
SELECT
        event_type                                                                     AS event_type,
        payload                                                                        AS payload,
        try_strptime(occurred_at, '%Y-%m-%d %H:%M:%S')                                 AS occurred_at,
        try_cast(nullif(trim(regexp_replace(amount, '^\$', '')), '') as DECIMAL(10,2)) AS amount
FROM {{ source('raw', 'raw_events') }}
