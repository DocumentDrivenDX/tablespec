-- uniqueness intent: PRIMARY KEY (member_id) is NOT enforced by LDP (snapshot/full-reload dataset; LDP has no row-local UNIQUE expectation -- relies on the source being unique per key).
CREATE OR REFRESH MATERIALIZED VIEW ingested_member
(
  CONSTRAINT not_null_member_id EXPECT (member_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS SELECT
        cast(nullif(trim(regexp_replace(member_id, '^\\$', '')), '') as INT) AS member_id,
        member_name                                                          AS member_name
FROM raw_member;