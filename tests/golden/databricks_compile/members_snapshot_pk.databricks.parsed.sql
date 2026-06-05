-- adapter: databricks
-- artifact: parsed_model_body (dbt parse raw_code; not compiled)
-- materialized: table
-- contract_enforced: True
{{
    config(
        materialized='table',
        contract={'enforced': True},
    )
}}

-- snapshot: full drop/reload (materialized table rebuild).
SELECT
        member_id                                                                           AS member_id,
        full_name                                                                           AS full_name,
        cast(try_to_timestamp(birth_date, 'yyyyMMdd') as date)                              AS birth_date,
        cast(enrolled as boolean)                                                           AS enrolled,
        cast(nullif(trim(regexp_replace(monthly_premium, '^\\$', '')), '') as DECIMAL(8,2)) AS monthly_premium
FROM {{ source('raw', 'raw_members') }}
