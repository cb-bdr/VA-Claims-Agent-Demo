-- ===========================================================================
-- GATED L3 authority functions -- bdr_labs.va_claims_tc
-- ===========================================================================

CREATE OR REPLACE FUNCTION bdr_labs.va_claims_tc.gated_health_check()
RETURNS STRING
LANGUAGE SQL
COMMENT 'MCP-enabling smoke test for the GATED authority function suite.'
RETURN 'GATED_OK: bdr_labs.va_claims_tc authority functions reachable';

-- ---------------------------------------------------------------------------
-- C1 (allowlist) + C3 (unambiguous custodian) -- static doc-type authority table
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION bdr_labs.va_claims_tc.check_doc_type_authority(p_doc_type STRING, p_custodian STRING)
RETURNS STRUCT<
  doc_type STRING,
  expected_custodian STRING,
  custodian_is_unambiguous BOOLEAN,
  on_l3_allowlist BOOLEAN,
  custodian_matches BOOLEAN,
  c1_pass BOOLEAN,
  c3_pass BOOLEAN
>
LANGUAGE SQL
COMMENT 'C1 (allowlist) and C3 (unambiguous custodian) lookup for the bounded L3 evidence-request lane.'
RETURN STRUCT(
  p_doc_type AS doc_type,
  element_at(
    map('STR','NPRC','VAMC_TREATMENT','VAMC','DD214','NPRC','PRIVATE_TREATMENT','PRIVATE_PROVIDER',
        'CANDP_EXAM','CONTRACT_EXAMINER','LAY_STATEMENT','CLAIMANT','FINANCIAL_STATEMENT','CLAIMANT',
        'SHELTER_LETTER','THIRD_PARTY','PHYSICIAN_STATEMENT','PRIVATE_PROVIDER','FORM_20_10207','CLAIMANT'),
    p_doc_type
  ) AS expected_custodian,
  element_at(
    map('STR',true,'VAMC_TREATMENT',true,'DD214',true,'PRIVATE_TREATMENT',false,'CANDP_EXAM',false,
        'LAY_STATEMENT',true,'FINANCIAL_STATEMENT',true,'SHELTER_LETTER',false,'PHYSICIAN_STATEMENT',false,
        'FORM_20_10207',true),
    p_doc_type
  ) AS custodian_is_unambiguous,
  (p_doc_type IN ('STR','VAMC_TREATMENT','DD214')) AS on_l3_allowlist,
  (element_at(
    map('STR','NPRC','VAMC_TREATMENT','VAMC','DD214','NPRC','PRIVATE_TREATMENT','PRIVATE_PROVIDER',
        'CANDP_EXAM','CONTRACT_EXAMINER','LAY_STATEMENT','CLAIMANT','FINANCIAL_STATEMENT','CLAIMANT',
        'SHELTER_LETTER','THIRD_PARTY','PHYSICIAN_STATEMENT','PRIVATE_PROVIDER','FORM_20_10207','CLAIMANT'),
    p_doc_type
  ) = p_custodian) AS custodian_matches,
  (p_doc_type IN ('STR','VAMC_TREATMENT','DD214')) AS c1_pass,
  (COALESCE(element_at(
    map('STR',true,'VAMC_TREATMENT',true,'DD214',true,'PRIVATE_TREATMENT',false,'CANDP_EXAM',false,
        'LAY_STATEMENT',true,'FINANCIAL_STATEMENT',true,'SHELTER_LETTER',false,'PHYSICIAN_STATEMENT',false,
        'FORM_20_10207',true),
    p_doc_type
  ), false)
   AND element_at(
    map('STR','NPRC','VAMC_TREATMENT','VAMC','DD214','NPRC','PRIVATE_TREATMENT','PRIVATE_PROVIDER',
        'CANDP_EXAM','CONTRACT_EXAMINER','LAY_STATEMENT','CLAIMANT','FINANCIAL_STATEMENT','CLAIMANT',
        'SHELTER_LETTER','THIRD_PARTY','PHYSICIAN_STATEMENT','PRIVATE_PROVIDER','FORM_20_10207','CLAIMANT'),
    p_doc_type
  ) = p_custodian) AS c3_pass
);

-- ---------------------------------------------------------------------------
-- C2: deterministic-absence check against document.index_status
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION bdr_labs.va_claims_tc.check_evidence_completeness(p_claim_id STRING, p_doc_type STRING)
RETURNS STRUCT<
  claim_id STRING,
  doc_type STRING,
  resolved_status STRING,
  c2_pass BOOLEAN,
  detail STRING
>
LANGUAGE SQL
COMMENT 'C2: distinguishes absent (deterministic, C2 passes) from received_not_indexed (ambiguous, C2 fails) from indexed (evidence already on file).'
RETURN (
  WITH agg AS (
    SELECT
      COUNT(*) AS n,
      SUM(CASE WHEN index_status = 'indexed' THEN 1 ELSE 0 END) AS n_indexed,
      SUM(CASE WHEN index_status = 'received_not_indexed' THEN 1 ELSE 0 END) AS n_pending
    FROM bdr_labs.va_claims_tc.document
    WHERE claim_id = p_claim_id AND doc_type = p_doc_type
  )
  SELECT STRUCT(
    p_claim_id AS claim_id,
    p_doc_type AS doc_type,
    CASE
      WHEN n = 0 THEN 'absent'
      WHEN n_indexed > 0 THEN 'indexed'
      WHEN n_pending > 0 THEN 'received_not_indexed'
      ELSE 'absent'
    END AS resolved_status,
    CASE
      WHEN n = 0 THEN true
      WHEN n_indexed > 0 THEN true
      WHEN n_pending > 0 THEN false
      ELSE true
    END AS c2_pass,
    CASE
      WHEN n = 0 THEN 'No record of this document type on file -- deterministic absence confirmed.'
      WHEN n_indexed > 0 THEN 'Document already indexed and on file -- not missing, do not request.'
      WHEN n_pending > 0 THEN 'Document received but not yet indexed -- absence is NOT deterministic, C2 fails.'
      ELSE 'Document on file with index_status=absent -- deterministic absence confirmed.'
    END AS detail
  )
  FROM agg
);

-- ---------------------------------------------------------------------------
-- Policy currency: citation + current/superseded status, never silently picks one
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION bdr_labs.va_claims_tc.check_policy_currency(p_policy_id STRING)
RETURNS STRUCT<
  policy_id STRING,
  citation STRING,
  title STRING,
  is_current BOOLEAN,
  superseded_by STRING,
  superseded_by_citation STRING,
  detail STRING
>
LANGUAGE SQL
COMMENT 'Returns policy citation plus current/superseded status; never silently resolves to one version.'
RETURN (
  SELECT STRUCT(
    MAX(p.policy_id) AS policy_id,
    MAX(p.citation) AS citation,
    MAX(p.title) AS title,
    BOOL_OR(p.is_current) AS is_current,
    MAX(p.superseded_by) AS superseded_by,
    MAX(s.citation) AS superseded_by_citation,
    MAX(CASE
      WHEN p.is_current THEN CONCAT('CURRENT: ', p.citation)
      ELSE CONCAT('SUPERSEDED: ', p.citation, ' -> see ', COALESCE(s.citation, p.superseded_by))
    END) AS detail
  )
  FROM bdr_labs.va_claims_tc.policy_reference p
  LEFT JOIN bdr_labs.va_claims_tc.policy_reference s ON s.policy_id = p.superseded_by
  WHERE p.policy_id = p_policy_id
);

-- ---------------------------------------------------------------------------
-- Combined C1-C5 verdict for the bounded L3 evidence-request lane
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION bdr_labs.va_claims_tc.evaluate_l3_authority(
  p_claim_id STRING, p_doc_type STRING, p_custodian STRING, p_action_type STRING
)
RETURNS STRUCT<
  claim_id STRING,
  doc_type STRING,
  verdict STRING,
  refusal_reason STRING,
  detail STRING
>
LANGUAGE SQL
COMMENT 'Combines C1 (allowlist), C2 (deterministic absence), C3 (unambiguous custodian) with C4 (non-adverse) / C5 (duty-to-assist) as static properties of action_type into one permit/refuse verdict.'
RETURN (
  WITH evidence AS (
    SELECT
      CASE
        WHEN COUNT(*) = 0 THEN 'absent'
        WHEN SUM(CASE WHEN index_status = 'indexed' THEN 1 ELSE 0 END) > 0 THEN 'indexed'
        WHEN SUM(CASE WHEN index_status = 'received_not_indexed' THEN 1 ELSE 0 END) > 0 THEN 'received_not_indexed'
        ELSE 'absent'
      END AS resolved_status
    FROM bdr_labs.va_claims_tc.document
    WHERE claim_id = p_claim_id AND doc_type = p_doc_type
  ),
  authz AS (
    SELECT
      (p_doc_type IN ('STR','VAMC_TREATMENT','DD214')) AS c1_pass,
      (COALESCE(element_at(
        map('STR',true,'VAMC_TREATMENT',true,'DD214',true,'PRIVATE_TREATMENT',false,'CANDP_EXAM',false,
            'LAY_STATEMENT',true,'FINANCIAL_STATEMENT',true,'SHELTER_LETTER',false,'PHYSICIAN_STATEMENT',false,
            'FORM_20_10207',true),
        p_doc_type
      ), false)
       AND element_at(
        map('STR','NPRC','VAMC_TREATMENT','VAMC','DD214','NPRC','PRIVATE_TREATMENT','PRIVATE_PROVIDER',
            'CANDP_EXAM','CONTRACT_EXAMINER','LAY_STATEMENT','CLAIMANT','FINANCIAL_STATEMENT','CLAIMANT',
            'SHELTER_LETTER','THIRD_PARTY','PHYSICIAN_STATEMENT','PRIVATE_PROVIDER','FORM_20_10207','CLAIMANT'),
        p_doc_type
      ) = p_custodian) AS c3_pass,
      evidence.resolved_status,
      (evidence.resolved_status IN ('absent', 'indexed')) AS c2_pass,
      (p_action_type = 'REQUEST_MISSING_EVIDENCE') AS c4_c5_pass
    FROM evidence
  )
  SELECT STRUCT(
    p_claim_id AS claim_id,
    p_doc_type AS doc_type,
    CASE WHEN c1_pass AND c3_pass AND c2_pass AND c4_c5_pass THEN 'permit' ELSE 'refuse' END AS verdict,
    CASE
      WHEN NOT c1_pass THEN 'C1_ALLOWLIST'
      WHEN NOT c3_pass THEN 'C3_UNAMBIGUOUS_CUSTODIAN'
      WHEN NOT c2_pass THEN 'C2_DETERMINISTIC_ABSENCE'
      WHEN NOT c4_c5_pass THEN 'C4_C5_ACTION_TYPE_OUT_OF_LANE (static property of action_type, not a per-case lookup)'
      ELSE NULL
    END AS refusal_reason,
    CASE
      WHEN NOT c1_pass THEN CONCAT('Doc type ', p_doc_type, ' is not on the L3 allowlist.')
      WHEN NOT c3_pass THEN CONCAT('Custodian for ', p_doc_type, ' is ambiguous or does not match the supplied value (', COALESCE(p_custodian, 'NULL'), ').')
      WHEN NOT c2_pass THEN CONCAT('Document status is ', resolved_status, ' -- absence is not deterministic, cannot autonomously act.')
      WHEN NOT c4_c5_pass THEN CONCAT('Action type ', p_action_type, ' is outside the non-adverse, duty-to-assist evidence-request lane.')
      ELSE 'All C1-C5 conditions satisfied for the bounded evidence-request lane.'
    END AS detail
  )
  FROM authz
);
