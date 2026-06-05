-- uniqueness intent: PRIMARY KEY (claim_id) is enforced by APPLY CHANGES ... KEYS (latest-per-key upsert).
CREATE OR REFRESH STREAMING TABLE ingested_claims
(
  CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) ON VIOLATION FAIL UPDATE
);

APPLY CHANGES INTO ingested_claims
FROM (
  SELECT
        claim_id                                                                          AS claim_id,
        cast(nullif(trim(regexp_replace(claim_amount, '^\\$', '')), '') as DECIMAL(18,2)) AS claim_amount,
        cast(try_to_timestamp(service_date, 'yyyyMMdd') as date)                          AS service_date,
        try_to_timestamp(submitted_at, 'MM/dd/yyyy HH:mm:ss')                             AS submitted_at,
        member_id                                                                         AS member_id,
        cast(is_paid as boolean)                                                          AS is_paid
  FROM STREAM raw_claims
)
KEYS (claim_id)
SEQUENCE BY _load_ts;