-- ============================================================================
-- Ingest plan: raw_provider_directory -> ingested_provider_directory
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: snapshot    Primary key: (none)    Order by: file_date_yyyymmdd
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_provider_directory (
    provider_npi  STRING,
    provider_name STRING,
    enrolled_date STRING,
    is_active     STRING,
    _source_file  STRING,
    _load_ts      TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_provider_directory (
    provider_npi  STRING NOT NULL,
    provider_name STRING,
    enrolled_date DATE,
    is_active     BOOLEAN
) USING DELTA
COMMENT 'Full provider directory snapshot';

-- 3. Raw -> ingested transform
-- WARNING: no primary_key + snapshot mode -> blind drop/reload.
-- WARNING: entire table is overwritten; no key-level reconciliation.
INSERT OVERWRITE ingested_provider_directory
    SELECT
        provider_npi                                                AS provider_npi,
        provider_name                                               AS provider_name,
        cast(try_to_timestamp(enrolled_date, 'MM/dd/yyyy') as date) AS enrolled_date,
        cast(is_active as boolean)                                  AS is_active
    FROM raw_provider_directory;
