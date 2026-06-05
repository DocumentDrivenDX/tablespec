-- uniqueness intent: PRIMARY KEY (entity_key) is enforced by APPLY CHANGES ... KEYS (latest-per-key upsert).
CREATE OR REFRESH STREAMING TABLE ingested_multibatch_ooo
(
  CONSTRAINT not_null_entity_key EXPECT (entity_key IS NOT NULL) ON VIOLATION FAIL UPDATE
);

APPLY CHANGES INTO ingested_multibatch_ooo
FROM (
  SELECT
        entity_key                                                                  AS entity_key,
        state                                                                       AS state,
        cast(nullif(trim(regexp_replace(revision, '^\\$', '')), '') as INT)         AS revision,
        cast(nullif(trim(regexp_replace(amount, '^\\$', '')), '') as DECIMAL(12,2)) AS amount
  FROM STREAM raw_multibatch_ooo
)
KEYS (entity_key)
SEQUENCE BY _load_ts;