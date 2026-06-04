-- ============================================================================
-- Ingest plan: raw_claims -> ingested_claims
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: incremental    Primary key: ['claim_id']    Order by: _load_ts
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_claims (
    claim_id     STRING,
    claim_amount STRING,
    service_date STRING,
    submitted_at STRING,
    member_id    STRING,
    is_paid      STRING,
    _source_file STRING,
    _load_ts     TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_claims (
    claim_id     STRING NOT NULL,
    claim_amount DECIMAL(18,2),
    service_date DATE,
    submitted_at TIMESTAMP,
    member_id    STRING,
    is_paid      BOOLEAN
) USING DELTA
COMMENT 'Healthcare claims';

-- 3. Raw -> ingested transform
MERGE INTO ingested_claims AS tgt
USING (
    SELECT
        claim_id                                                                          AS claim_id,
        cast(nullif(trim(regexp_replace(claim_amount, '^\\$', '')), '') as DECIMAL(18,2)) AS claim_amount,
        cast(try_to_timestamp(service_date, 'yyyyMMdd') as date)                          AS service_date,
        try_to_timestamp(submitted_at, 'MM/dd/yyyy HH:mm:ss')                             AS submitted_at,
        member_id                                                                         AS member_id,
        cast(is_paid as boolean)                                                          AS is_paid
    FROM (
        SELECT * FROM (
            SELECT *, row_number() OVER (PARTITION BY claim_id ORDER BY _load_ts DESC) AS _rn
            FROM raw_claims
        ) WHERE _rn = 1
    ) src_raw
) AS src
ON tgt.claim_id = src.claim_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;
