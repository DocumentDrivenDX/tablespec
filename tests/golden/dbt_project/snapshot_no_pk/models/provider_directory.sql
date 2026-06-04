{{
    config(
        materialized='table',
    )
}}

-- snapshot: full drop/reload (materialized table rebuild).
SELECT
        provider_npi                                          AS provider_npi,
        provider_name                                         AS provider_name,
        cast(try_strptime(enrolled_date, '%m/%d/%Y') as date) AS enrolled_date,
        try_cast(is_active as boolean)                        AS is_active
FROM {{ source('raw', 'raw_provider_directory') }}
