{{
    config(
        materialized='incremental',
        on_schema_change='fail',
        contract={'enforced': True},
    )
}}

-- WARNING: no primary_key + incremental -> blind append (no dedup).
-- Contract: raw source holds ONE batch per run; duplicates accumulate
-- on re-ingest of the same rows (matches the Spark INSERT INTO branch).
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
FROM {{ source('raw', 'raw_encounter') }}
