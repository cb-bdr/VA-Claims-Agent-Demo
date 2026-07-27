# Genie space — VA Claims Agent Demo

Genie configuration is **workspace-specific** and may not be fully expressible in Asset Bundle YAML on all releases. Use this checklist after `databricks bundle deploy` and the first successful SDP run.

## 1. Trusted data

Attach Unity Catalog tables (defaults):

- `{catalog}.{schema}.claims` (e.g. `bdr_labs.vba_claims_agent.claims`)
- `{catalog}.{schema}.gold_claims_timeseries`
- Optional: `silver_va_doc_chunk`, `silver_dim_icd10`, `silver_observation_loinc`

Use the same `catalog` / `schema` as in [databricks.yml](../databricks.yml) variables.

## 2. Space instructions (paste into Genie)

```markdown
You assist VA claims analysts reviewing synthetic demo data. Ground answers in the attached tables only.

Definitions:
- current_status: PENDING, DECISION_READY, REVIEW_REQUIRED, AWAITING_EVIDENCE, APPROVED, DENIED, etc.
- is_pact_act_eligible: PACT Act–related exposure scenarios in this demo.
- fraud_score / compliance_score: synthetic risk signals — not real fraud determinations.

Rules:
- Do not invent veteran PHI or real individuals.
- If asked for policy interpretation, say you only summarize patterns in the data unless a doc chunk table is attached.
- Prefer SQL over speculation; cite table and column names when explaining logic.
```

## 3. Sample prompts

1. How many claims are in each `current_status` this week?
2. Which weeks had the most PACT-eligible claims in `gold_claims_timeseries`?
3. List three `claimed_condition` values with the highest average `fraud_score` in `claims`.
4. Join observations: which LOINC codes appear most in `silver_observation_loinc`?
5. What topic_tags exist in `silver_va_doc_chunk`?

## 4. Link from the Databricks App

Set `VITE_GENIE_SPACE_URL` at **frontend build time** to the Genie URL your workspace provides (see [.env.example](../../.env.example)).

## 5. Automation

If your tenant exposes a **Genie REST API**, store the space ID in a secret and call it from a job; keep instructions versioned in this file.
