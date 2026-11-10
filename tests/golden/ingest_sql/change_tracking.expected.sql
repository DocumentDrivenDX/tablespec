-- SPDX-License-Identifier: MIT OR Apache-2.0
-- ============================================================================
-- Ingest plan: raw_claim_header -> ingested_claim_header
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: change_tracking    Primary key: ['claim_header_id']    Order by: _load_ts
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_claim_header (
    claim_header_id      STRING,
    billed_amount        STRING,
    status               STRING,
    legacy_code          STRING,
    CT_claim_header_id   STRING,
    SYS_CHANGE_OPERATION STRING,
    _source_file         STRING,
    _load_ts             TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_claim_header (
    claim_header_id      BIGINT NOT NULL,
    billed_amount        DECIMAL(12,2),
    status               STRING,
    legacy_code          STRING
) USING DELTA
COMMENT 'Claim headers from a SQL Server Change Tracking export';

-- 3. Raw -> ingested transform
-- change_tracking: latest SYS_CHANGE_OPERATION per key (order_by: _load_ts)
MERGE INTO ingested_claim_header AS tgt
USING (
    SELECT
        try_cast(nullif(trim(regexp_replace(coalesce(CT_claim_header_id, claim_header_id), '^\\$', '')), '') as BIGINT) AS claim_header_id,
        try_cast(nullif(trim(regexp_replace(billed_amount, '^\\$', '')), '') as DECIMAL(12,2))                          AS billed_amount,
        status                                                                                                          AS status,
        legacy_code                                                                                                     AS legacy_code,
        SYS_CHANGE_OPERATION AS _ct_operation
    FROM (
        SELECT * FROM (
            SELECT *, row_number() OVER (PARTITION BY coalesce(CT_claim_header_id, claim_header_id) ORDER BY _load_ts DESC) AS _rn
            FROM raw_claim_header
        ) WHERE _rn = 1
    ) src_raw
) AS src
ON tgt.claim_header_id = src.claim_header_id
WHEN MATCHED AND src._ct_operation IN ('D') THEN DELETE
WHEN MATCHED THEN UPDATE SET tgt.claim_header_id = src.claim_header_id, tgt.billed_amount = src.billed_amount, tgt.status = src.status, tgt.legacy_code = src.legacy_code
WHEN NOT MATCHED AND src._ct_operation NOT IN ('D') THEN
    INSERT (claim_header_id, billed_amount, status, legacy_code) VALUES (src.claim_header_id, src.billed_amount, src.status, src.legacy_code);
