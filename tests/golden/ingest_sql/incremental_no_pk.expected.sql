-- ============================================================================
-- Ingest plan: raw_events -> ingested_events
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: incremental    Primary key: (none)    Order by: _load_ts
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_events (
    event_type  STRING,
    payload     STRING,
    occurred_at STRING,
    amount      STRING,
    _source_file STRING,
    _load_ts    TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_events (
    event_type  STRING,
    payload     STRING,
    occurred_at TIMESTAMP,
    amount      DECIMAL(10,2)
) USING DELTA
COMMENT 'Raw event stream with no natural key';

-- 3. Raw -> ingested transform
-- WARNING: no primary_key + incremental mode -> cannot dedup/upsert.
-- WARNING: appending blindly; duplicate rows are possible on re-ingest.
INSERT INTO ingested_events
    SELECT
        event_type                                                                  AS event_type,
        payload                                                                     AS payload,
        try_to_timestamp(occurred_at, 'yyyy-MM-dd HH:mm:ss')                        AS occurred_at,
        cast(nullif(trim(regexp_replace(amount, '^\\$', '')), '') as DECIMAL(10,2)) AS amount
    FROM raw_events;
