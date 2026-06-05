-- uniqueness intent: PRIMARY KEY (member_id) is NOT enforced by LDP (snapshot/full-reload dataset; LDP has no row-local UNIQUE expectation -- relies on the source being unique per key).
CREATE OR REFRESH MATERIALIZED VIEW ingested_members
(
  CONSTRAINT not_null_member_id EXPECT (member_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        member_id                                                                           AS member_id,
        full_name                                                                           AS full_name,
        cast(try_to_timestamp(birth_date, 'yyyyMMdd') as date)                              AS birth_date,
        cast(enrolled as boolean)                                                           AS enrolled,
        cast(nullif(trim(regexp_replace(monthly_premium, '^\\$', '')), '') as DECIMAL(8,2)) AS monthly_premium
FROM raw_members;