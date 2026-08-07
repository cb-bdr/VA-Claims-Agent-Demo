-- Queries used to generate VA_CLAIMS_AI_TABLES.md (2026-07-28).
-- Run against bdr_labs.vba_claims_agent to refresh the doc. Do not hand-edit
-- VA_CLAIMS_AI_TABLES.md's facts without re-running these — every claim in
-- that doc must trace back to a live query, not to memory or inference.

-- ============================================================
-- Step 1: DESCRIBE TABLE for all 14 materialized views
-- ============================================================

DESCRIBE TABLE bdr_labs.vba_claims_agent.bronze_ccda_manifest;
DESCRIBE TABLE bdr_labs.vba_claims_agent.bronze_cerner_claim_extract;
DESCRIBE TABLE bdr_labs.vba_claims_agent.bronze_fhir_bundle;
DESCRIBE TABLE bdr_labs.vba_claims_agent.bronze_vista_event;
DESCRIBE TABLE bdr_labs.vba_claims_agent.claim_evidence;
DESCRIBE TABLE bdr_labs.vba_claims_agent.claim_history;
DESCRIBE TABLE bdr_labs.vba_claims_agent.claims;
DESCRIBE TABLE bdr_labs.vba_claims_agent.gold_adjudication_reports;
DESCRIBE TABLE bdr_labs.vba_claims_agent.gold_claims_timeseries;
DESCRIBE TABLE bdr_labs.vba_claims_agent.silver_dim_icd10;
DESCRIBE TABLE bdr_labs.vba_claims_agent.silver_dim_loinc;
DESCRIBE TABLE bdr_labs.vba_claims_agent.silver_dim_snomed;
DESCRIBE TABLE bdr_labs.vba_claims_agent.silver_observation_loinc;
DESCRIBE TABLE bdr_labs.vba_claims_agent.silver_va_doc_chunk;

-- claims and gold_adjudication_reports: EXTENDED to surface table comments
-- (this is how "gold_adjudication_reports is a literal alias of claims" was confirmed)
DESCRIBE TABLE EXTENDED bdr_labs.vba_claims_agent.claims;
DESCRIBE TABLE EXTENDED bdr_labs.vba_claims_agent.gold_adjudication_reports;

-- ============================================================
-- Step 2: row counts for all 14 tables
-- ============================================================

SELECT 'bronze_ccda_manifest' as tbl, COUNT(*) as rows FROM bdr_labs.vba_claims_agent.bronze_ccda_manifest
UNION ALL SELECT 'bronze_cerner_claim_extract', COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract
UNION ALL SELECT 'bronze_fhir_bundle', COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_fhir_bundle
UNION ALL SELECT 'bronze_vista_event', COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_vista_event
UNION ALL SELECT 'claim_evidence', COUNT(*) FROM bdr_labs.vba_claims_agent.claim_evidence
UNION ALL SELECT 'claim_history', COUNT(*) FROM bdr_labs.vba_claims_agent.claim_history
UNION ALL SELECT 'claims', COUNT(*) FROM bdr_labs.vba_claims_agent.claims
UNION ALL SELECT 'gold_adjudication_reports', COUNT(*) FROM bdr_labs.vba_claims_agent.gold_adjudication_reports
UNION ALL SELECT 'gold_claims_timeseries', COUNT(*) FROM bdr_labs.vba_claims_agent.gold_claims_timeseries
UNION ALL SELECT 'silver_dim_icd10', COUNT(*) FROM bdr_labs.vba_claims_agent.silver_dim_icd10
UNION ALL SELECT 'silver_dim_loinc', COUNT(*) FROM bdr_labs.vba_claims_agent.silver_dim_loinc
UNION ALL SELECT 'silver_dim_snomed', COUNT(*) FROM bdr_labs.vba_claims_agent.silver_dim_snomed
UNION ALL SELECT 'silver_observation_loinc', COUNT(*) FROM bdr_labs.vba_claims_agent.silver_observation_loinc
UNION ALL SELECT 'silver_va_doc_chunk', COUNT(*) FROM bdr_labs.vba_claims_agent.silver_va_doc_chunk;

-- Date ranges per table with a date-like column (don't assume every table
-- shares the claims snapshot window without checking)
SELECT MIN(date_submitted), MAX(date_submitted) FROM bdr_labs.vba_claims_agent.claims;
SELECT MIN(date_submitted), MAX(date_submitted) FROM bdr_labs.vba_claims_agent.gold_adjudication_reports;
SELECT MIN(week_start), MAX(week_start) FROM bdr_labs.vba_claims_agent.gold_claims_timeseries;
SELECT MIN(event_dt), MAX(event_dt) FROM bdr_labs.vba_claims_agent.bronze_vista_event;
SELECT MIN(service_date), MAX(service_date) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract;
SELECT MIN(effective_time), MAX(effective_time) FROM bdr_labs.vba_claims_agent.bronze_ccda_manifest;
SELECT MIN(action_date), MAX(action_date) FROM bdr_labs.vba_claims_agent.claim_history;

-- ============================================================
-- Step 3: confirmed relationships / non-relationships (real join tests,
-- not assumptions from column naming)
-- ============================================================

-- claim_evidence -> claims (confirmed exhaustive: 480/480 rows, 120/120 distinct claims)
SELECT
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.claim_evidence) as evidence_rows,
  (SELECT COUNT(DISTINCT claim_id) FROM bdr_labs.vba_claims_agent.claim_evidence) as evidence_distinct_claims,
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.claim_evidence e JOIN bdr_labs.vba_claims_agent.claims c ON e.claim_id = c.claim_id) as evidence_joined_rows,
  (SELECT COUNT(DISTINCT e.claim_id) FROM bdr_labs.vba_claims_agent.claim_evidence e JOIN bdr_labs.vba_claims_agent.claims c ON e.claim_id = c.claim_id) as evidence_joined_distinct_claims;

-- claim_history -> claims (confirmed exhaustive: 360/360 rows, 120/120 distinct claims)
SELECT
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.claim_history) as history_rows,
  (SELECT COUNT(DISTINCT claim_id) FROM bdr_labs.vba_claims_agent.claim_history) as history_distinct_claims,
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.claim_history h JOIN bdr_labs.vba_claims_agent.claims c ON h.claim_id = c.claim_id) as history_joined_rows,
  (SELECT COUNT(DISTINCT h.claim_id) FROM bdr_labs.vba_claims_agent.claim_history h JOIN bdr_labs.vba_claims_agent.claims c ON h.claim_id = c.claim_id) as history_joined_distinct_claims;

-- bronze_cerner_claim_extract -> claims / bronze_ccda_manifest
-- (cerner_claim_id = claim_id joins 120/120 -- corrects an earlier wrong assumption
-- that this table had no join path to claims)
SELECT
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract) as extract_rows,
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract e JOIN bdr_labs.vba_claims_agent.claims c ON e.cerner_claim_id = c.claim_id) as joined_by_cerner_id,
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract e JOIN bdr_labs.vba_claims_agent.bronze_ccda_manifest m ON e.cerner_claim_id = m.linked_cerner_claim_id) as ccda_joined;

-- bronze_cerner_claim_extract.icd10_cm_code -> silver_dim_icd10.icd10_code (120/120 clean)
SELECT
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract) as extract_rows,
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_cerner_claim_extract e JOIN bdr_labs.vba_claims_agent.silver_dim_icd10 d ON e.icd10_cm_code = d.icd10_code) as joined_rows;

-- silver_observation_loinc.loinc_code -> silver_dim_loinc.loinc_num (200/200 clean)
SELECT
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.silver_observation_loinc) as obs_rows,
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.silver_observation_loinc o JOIN bdr_labs.vba_claims_agent.silver_dim_loinc d ON o.loinc_code = d.loinc_num) as joined_rows;

-- bronze_vista_event key cardinality (confirms no claim_id/cerner_claim_id column
-- exists at all -- no join path to claims, structurally, not just untested)
SELECT
  (SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.bronze_vista_event) as vista_rows,
  (SELECT COUNT(DISTINCT dfn) FROM bdr_labs.vba_claims_agent.bronze_vista_event) as distinct_dfn,
  (SELECT COUNT(DISTINCT icn) FROM bdr_labs.vba_claims_agent.bronze_vista_event) as distinct_icn;

-- ============================================================
-- Step 4: cross-reference against what claims_service.py actually uses
-- ============================================================

-- grep -n "self.schema}\.\|FROM {self" server/services/claims_service.py
