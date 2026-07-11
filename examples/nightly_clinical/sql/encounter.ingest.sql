-- ============================================================================
-- Ingest plan: raw_encounter -> ingested_encounter
-- ============================================================================
-- Generated from UMF. Casts mirror casting_utils.cast_column_sql.
-- Mode: incremental    Primary key: (none)    Order by: _load_ts
-- ============================================================================

-- 1. Raw landing table
CREATE TABLE IF NOT EXISTS raw_encounter (
    encounter_id                STRING,
    person_id                   STRING,
    patient_id                  STRING,
    encounter_type              STRING,
    encounter_start_date        STRING,
    encounter_end_date          STRING,
    admit_source_code           STRING,
    admit_type_code             STRING,
    discharge_disposition_code  STRING,
    attending_provider_id       STRING,
    facility_npi                STRING,
    facility_name               STRING,
    primary_diagnosis_code_type STRING,
    primary_diagnosis_code      STRING,
    drg_code_type               STRING,
    drg_code                    STRING,
    paid_amount                 STRING,
    allowed_amount              STRING,
    charge_amount               STRING,
    ingest_datetime             STRING,
    data_source                 STRING,
    attending_provider_name     STRING,
    META_data_source            STRING,
    META_Load_DTTM              STRING,
    _source_file                STRING,
    _load_ts                    TIMESTAMP
) USING DELTA
COMMENT 'Raw landing zone -- untyped, as received';

-- 2. Typed target table
CREATE TABLE IF NOT EXISTS ingested_encounter (
    encounter_id                STRING,
    person_id                   STRING,
    patient_id                  STRING,
    encounter_type              STRING,
    encounter_start_date        DATE,
    encounter_end_date          DATE,
    admit_source_code           STRING,
    admit_type_code             STRING,
    discharge_disposition_code  STRING,
    attending_provider_id       STRING,
    facility_npi                STRING,
    facility_name               STRING,
    primary_diagnosis_code_type STRING,
    primary_diagnosis_code      STRING,
    drg_code_type               STRING,
    drg_code                    STRING,
    paid_amount                 FLOAT,
    allowed_amount              FLOAT,
    charge_amount               FLOAT,
    ingest_datetime             TIMESTAMP,
    data_source                 STRING,
    attending_provider_name     STRING,
    META_data_source            STRING,
    META_Load_DTTM              TIMESTAMP
) USING DELTA;

-- 3. Raw -> ingested transform
-- WARNING: no primary_key + incremental mode -> cannot dedup/upsert.
-- WARNING: appending blindly; duplicate rows are possible on re-ingest.
INSERT INTO ingested_encounter
    SELECT
        encounter_id                                                                 AS encounter_id,
        person_id                                                                    AS person_id,
        patient_id                                                                   AS patient_id,
        encounter_type                                                               AS encounter_type,
        cast(try_to_timestamp(encounter_start_date) as date)                         AS encounter_start_date,
        cast(try_to_timestamp(encounter_end_date) as date)                           AS encounter_end_date,
        admit_source_code                                                            AS admit_source_code,
        admit_type_code                                                              AS admit_type_code,
        discharge_disposition_code                                                   AS discharge_disposition_code,
        attending_provider_id                                                        AS attending_provider_id,
        facility_npi                                                                 AS facility_npi,
        facility_name                                                                AS facility_name,
        primary_diagnosis_code_type                                                  AS primary_diagnosis_code_type,
        primary_diagnosis_code                                                       AS primary_diagnosis_code,
        drg_code_type                                                                AS drg_code_type,
        drg_code                                                                     AS drg_code,
        cast(nullif(trim(regexp_replace(paid_amount, '^\\$', '')), '') as DOUBLE)    AS paid_amount,
        cast(nullif(trim(regexp_replace(allowed_amount, '^\\$', '')), '') as DOUBLE) AS allowed_amount,
        cast(nullif(trim(regexp_replace(charge_amount, '^\\$', '')), '') as DOUBLE)  AS charge_amount,
        try_to_timestamp(ingest_datetime)                                            AS ingest_datetime,
        data_source                                                                  AS data_source,
        attending_provider_name                                                      AS attending_provider_name,
        META_data_source                                                             AS META_data_source,
        try_to_timestamp(META_Load_DTTM)                                             AS META_Load_DTTM
    FROM raw_encounter;