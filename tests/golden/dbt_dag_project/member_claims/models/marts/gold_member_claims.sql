{{
    config(
        materialized='table',
    )
}}

-- ============================================================================
-- SQL Execution Plan: member_claims
-- ============================================================================
-- Purpose: Build member_claims dataset through sequential joins
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
  member_id,
  claim_amount
FROM {{ ref('ingested_claims') }}
),

disposition_step_1 AS (
-- ============================================================================
-- STEP 1: Join member (Direct Join - 1:1)
-- ============================================================================
SELECT
  base.claim_amount,
  base.claim_id,
  base.member_id,
  target.member_name AS member__member_name,
  target.state AS member__state
FROM disposition_base base
LEFT JOIN {{ ref('ingested_member') }} target
  ON base.member_id = target.member_id
),

member_claims AS (
-- ============================================================================
-- FINAL ASSEMBLY: member_claims with Column Derivations
-- ============================================================================
SELECT
  base.claim_amount AS claim_amount,
  base.claim_id AS claim_id,
  base.member_id AS member_id,
  base.member__member_name AS member_name,
  base.member__state AS member_state
FROM disposition_step_1 base
)
SELECT * FROM member_claims
