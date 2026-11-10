-- SPDX-License-Identifier: MIT OR Apache-2.0
-- ============================================================================
-- Ingest plan: raw_claim_events -> ingested_claim_events
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: append    Primary key: ['event_id']    Order by: _load_ts
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_claim_events (
    event_id   STRING,
    claim_id   STRING,
    status     STRING,
    event_date STRING,
    _source_file STRING,
    _load_ts   TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_claim_events (
    event_id   BIGINT NOT NULL,
    claim_id   STRING NOT NULL,
    status     STRING,
    event_date DATE
) USING DELTA
COMMENT 'Claim status events (history; every delivery row is kept)';

-- 3. Raw -> ingested transform
-- append mode: every landed row is kept (no dedup, no overwrite).
INSERT INTO ingested_claim_events
    SELECT
        try_cast(nullif(trim(regexp_replace(event_id, '^\\$', '')), '') as BIGINT) AS event_id,
        claim_id                                                                   AS claim_id,
        status                                                                     AS status,
        cast(try_to_timestamp(event_date, 'yyyy-MM-dd') as date)                   AS event_date
    FROM raw_claim_events;
