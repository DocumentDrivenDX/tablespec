-- SPDX-License-Identifier: MIT OR Apache-2.0
-- ============================================================================
-- Ingest plan: raw_claim_header_rebuild -> ingested_claim_header_rebuild
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: change_tracking    Primary key: ['claim_header_id']    Order by: _load_ts
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_claim_header_rebuild (
    claim_header_id      STRING,
    billed_amount        STRING,
    status               STRING,
    legacy_code          STRING,
    CT_claim_header_id   STRING,
    SYS_CHANGE_OPERATION STRING,
    SYS_CHANGE_VERSION   STRING,
    _source_file         STRING,
    _load_ts             TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_claim_header_rebuild (
    claim_header_id      BIGINT NOT NULL,
    billed_amount        DECIMAL(12,2),
    status               STRING,
    legacy_code          STRING
) USING DELTA
COMMENT 'Claim headers from a SQL Server Change Tracking export (rebuild from full history)';

-- 3. Raw -> ingested transform
-- change_tracking (rebuild): live state from the full raw history; the newest
-- baseline (by _load_ts) supersedes earlier rows (order_by: _load_ts, try_cast(SYS_CHANGE_VERSION as BIGINT))
INSERT OVERWRITE ingested_claim_header_rebuild
    SELECT
        try_cast(nullif(trim(regexp_replace(coalesce(CT_claim_header_id, claim_header_id), '^\\$', '')), '') as BIGINT) AS claim_header_id,
        try_cast(nullif(trim(regexp_replace(billed_amount, '^\\$', '')), '') as DECIMAL(12,2))                          AS billed_amount,
        status                                                                                                          AS status,
        legacy_code                                                                                                     AS legacy_code
    FROM (
        SELECT * FROM (
            SELECT *, row_number() OVER (PARTITION BY coalesce(CT_claim_header_id, claim_header_id) ORDER BY _load_ts DESC, try_cast(SYS_CHANGE_VERSION as BIGINT) DESC) AS _rn
            FROM (
                SELECT c.* FROM (SELECT *, upper(trim(SYS_CHANGE_OPERATION)) AS _ct_operation FROM raw_claim_header_rebuild) AS c
                CROSS JOIN (
                    SELECT max(_load_ts) AS _ct_baseline FROM (SELECT *, upper(trim(SYS_CHANGE_OPERATION)) AS _ct_operation FROM raw_claim_header_rebuild) AS b
                    WHERE (b._ct_operation IS NULL OR b._ct_operation = '')
                ) AS nb
                WHERE nb._ct_baseline IS NULL
                   OR ((c._ct_operation IS NULL OR c._ct_operation = '') AND c._load_ts = nb._ct_baseline)
                   OR (NOT (c._ct_operation IS NULL OR c._ct_operation = '') AND c._load_ts > nb._ct_baseline)
            ) AS scoped
        ) WHERE _rn = 1 AND NOT coalesce(_ct_operation IN ('D'), false)
    ) src_raw;
