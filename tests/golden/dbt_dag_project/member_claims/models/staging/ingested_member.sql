{{
    config(
        materialized='table',
    )
}}

-- snapshot: full drop/reload (materialized table rebuild).
SELECT
        try_cast(nullif(trim(regexp_replace(member_id, '^\$', '')), '') as INT) AS member_id,
        member_name                                                             AS member_name,
        state                                                                   AS state
FROM {{ source('raw', 'raw_member') }}
