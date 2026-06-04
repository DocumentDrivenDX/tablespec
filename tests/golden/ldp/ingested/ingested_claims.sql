-- uniqueness intent: PRIMARY KEY (claim_id) is enforced by APPLY CHANGES ... KEYS (latest-per-key upsert).
-- relationship intent: member_id -> ingested_member.member_id (referential integrity needs the parent dataset; not a row-local EXPECT).
CREATE OR REFRESH STREAMING TABLE ingested_claims
(
  CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT accepted_values_status EXPECT (status IS NULL OR status IN ('PAID', 'DENIED', 'PENDING')) ON VIOLATION FAIL UPDATE
);

APPLY CHANGES INTO ingested_claims
FROM (
  SELECT
        cast(nullif(trim(regexp_replace(claim_id, '^\\$', '')), '') as INT)               AS claim_id,
        cast(nullif(trim(regexp_replace(member_id, '^\\$', '')), '') as INT)              AS member_id,
        cast(nullif(trim(regexp_replace(claim_amount, '^\\$', '')), '') as DECIMAL(18,2)) AS claim_amount,
        status                                                                            AS status
  FROM STREAM raw_claims
)
KEYS (claim_id)
SEQUENCE BY _load_ts;