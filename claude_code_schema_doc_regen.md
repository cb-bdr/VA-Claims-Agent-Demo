# Task: Regenerate VA_CLAIMS_AI_TABLES.md from live schema

## Why

This doc has been wrong twice tonight (`claims_metrics`, `provider_delays` —
tables that don't exist) and caused two rounds of debugging that a live schema
check would have prevented. It currently only has a warning banner bolted onto
otherwise-stale content. Before Genie configuration begins — which depends on
people reading this doc to understand the semantic layer — it needs to be
regenerated from ground truth, not patched again.

## Rule for this task

**Every claim in the new doc must be traceable to an actual command run against
the live warehouse tonight, not to memory, not to the old doc, not to
inference.** If something can't be verified by a command, mark it
`UNVERIFIED` rather than stating it as fact — that's exactly the mistake that
produced tonight's bugs in the first place.

## Step 1 — Pull DESCRIBE output for all 14 tables

```sql
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
```

For `claims` and `gold_adjudication_reports` specifically, also run
`DESCRIBE TABLE EXTENDED` (already confirmed identical column sets tonight —
extended output may still surface useful comments/properties not seen in the
plain DESCRIBE).

## Step 2 — Row counts and date ranges for every table

Not just `claims` (already known: 120 rows, 2024-01-01 to 2024-11-23). Get this
for all 14, so the doc states real cardinality rather than assuming every table
matches the `claims` snapshot window:

```sql
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
```

Note in the doc, per table, whether it appears to be a static snapshot (like
`claims`) or something else — don't assume all 14 share the same 2024 window
without checking.

## Step 3 — Document confirmed relationships (and confirmed NON-relationships)

This is the most valuable part of tonight's investigation and the least
likely to survive if not written down explicitly. State plainly, as
already-confirmed facts:

- `claims` and `gold_adjudication_reports` have **identical column sets**
  (list them once, note both tables share it).
- `status` and `current_status` on `claims`/`gold_adjudication_reports` are
  **always identical in the current data** — this is a data coincidence, not
  an enforced constraint. Code should prefer `current_status`.
- Confirmed `current_status` vocabulary: `PENDING`, `DECISION_READY`,
  `REVIEW_REQUIRED`, `AWAITING_EVIDENCE`, `APPROVED`. **No `ACTIVE`, `DENIED`,
  or `DELAYED`** — state this explicitly as a "do not assume these values
  exist" warning, since guessing this vocabulary caused real bugs tonight.
- `presumptive_match` and `is_pact_act_eligible` are **BOOLEAN**, not
  INT — comparisons must use `= true`/`= false` or the bare column, never
  `= 1`/`= 0`. State this as a hard rule given it broke two methods tonight.
- `bronze_cerner_claim_extract.facility_id` and `bronze_vista_event.station_id`
  are the only facility/region-like fields anywhere in the schema, and
  **neither joins to `claims.claim_id`, and neither table has a duration
  field**. State explicitly: **there is no provider/region/delay-hours data
  source anywhere in this schema.** This is why `get_visibility_gaps` and
  `get_region_delays` fall back to mock data — link to that code comment.
- Any other join keys actually verified to work (e.g. does `claim_evidence` or
  `claim_history` join to `claims.claim_id` cleanly? Check with an actual
  `SELECT COUNT(*)` join query, don't assume from column naming).

## Step 4 — Cross-reference against what the code actually uses

```bash
grep -n "self.schema}\.\|FROM {self" server/services/claims_service.py
```

For each table referenced, note in the doc which method(s) use it and what
columns they read — this makes the doc directly useful for anyone extending
`claims_service.py` later, rather than a generic schema dump.

## Step 5 — Write the new file

Structure:

```markdown
# VA Claims AI — Live Schema Reference

> Regenerated [date] directly from `DESCRIBE TABLE` / `DESCRIBE EXTENDED` /
> `COUNT(*)` output against bdr_labs.vba_claims_agent. Every fact below was
> verified by a live query on this date — see the queries in
> scripts/regen_schema_doc_queries.sql (save the actual queries used, so this
> is re-runnable later; do not hand-maintain this file going forward).
>
> Previous versions of this doc referenced `claims_metrics` and
> `provider_delays`, which do not exist and never have in this schema. If this
> doc is ever found to disagree with a live `DESCRIBE TABLE`, trust the
> database, not this file, and regenerate.

## Tables (14 materialized views)

[one section per table: full column list with types, row count, date range if
applicable, one-line description of what it contains]

## Confirmed relationships

[Step 3 content]

## Confirmed NON-relationships (do not assume these joins exist)

[Step 3 content — the facility_id/station_id non-join, explicitly]

## Known data quirks

- Static 2024 snapshot, not a live feed — any `CURRENT_DATE`-relative filter
  will silently return zero rows. Anchor recency windows to
  `MAX(date_submitted)` instead.
- [any other quirks discovered in Step 2]

## Used by claims_service.py

[Step 4 content]
```

## Step 6 — Save the actual queries used

Put every query from Steps 1-4 into a new file, e.g.
`scripts/regen_schema_doc_queries.sql`, with a header comment explaining it's
what generated the doc above and should be re-run (not hand-edited around)
whenever the pipeline schema changes.

## Step 7 — Report back

- Full path to the new doc
- Confirm zero references remain to `claims_metrics` or `provider_delays`
  anywhere in the new file
- Flag anything from Steps 1-4 that came back surprising or inconsistent with
  what's already known (e.g., if `claim_evidence`/`claim_history` turn out
  NOT to join cleanly to `claims`, that's worth a callout, not a silent note)
- Confirm the file explicitly states "trust the database over this doc" so
  the failure mode from tonight is harder to repeat even if this doc drifts
  again later
