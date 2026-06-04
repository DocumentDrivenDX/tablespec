-- uniqueness intent: PRIMARY KEY (claim_id) is NOT enforced by LDP (snapshot/full-reload dataset; LDP has no row-local UNIQUE expectation -- relies on the source being unique per key).
-- relationship intent: member_id -> ingested_member.member_id (referential integrity needs the parent dataset; not a row-local EXPECT).
CREATE OR REFRESH MATERIALIZED VIEW gold_enriched
(
  CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) ON VIOLATION FAIL UPDATE
)
AS
-- ============================================================================
-- SQL Execution Plan: enriched
-- ============================================================================
-- Purpose: Build enriched dataset through sequential joins
-- Base Table: claims (hub table)
-- Total Joins: 1
-- Strategy: Pure SQL with temporary views for transparency
-- ============================================================================

-- ============================================================================
-- STEP 0: Create base view from claims
-- ============================================================================
WITH
disposition_base AS (
SELECT
  claim_id,
  member_id
FROM ingested_claims
),

member_first AS (
-- ============================================================================
-- STEP 1: Join member (First Record - 1:0..N)
-- ============================================================================
SELECT
  member_id,
    member_name
FROM (
  SELECT
    member_id,
    member_name,
    ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY member_name) as rn
  FROM ingested_member
) ranked
WHERE rn = 1
),

disposition_step_1 AS (
SELECT
  base.claim_id,
  base.member_id,
  target.member_name AS member__member_name
FROM disposition_base base
LEFT JOIN member_first target
  ON base.claim_id = target.member_id
),

enriched AS (
-- ============================================================================
-- FINAL ASSEMBLY: enriched with Column Derivations
-- ============================================================================
SELECT
  base.claim_id AS claim_id,
  base.member_id AS member_id,
  base.member__member_name AS member_name
FROM disposition_step_1 base
)
SELECT * FROM enriched;