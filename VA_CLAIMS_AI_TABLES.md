# VA Claims AI — Live Schema Reference

> Regenerated 2026-07-28 directly from `DESCRIBE TABLE` / `DESCRIBE TABLE EXTENDED` /
> `COUNT(*)` / join-test output against `bdr_labs.vba_claims_agent`, run against SQL
> warehouse `f55e003d2e50b597`. Every fact below was verified by a live query on this
> date — see the exact queries in
> [`scripts/regen_schema_doc_queries.sql`](scripts/regen_schema_doc_queries.sql)
> (re-run that file to refresh this doc later; do not hand-edit facts back in).
>
> Previous versions of this doc referenced `claims_metrics` and `provider_delays`,
> which do not exist and never have in this schema. **If this doc is ever found to
> disagree with a live `DESCRIBE TABLE`, trust the database, not this file, and
> regenerate.**

## Unity Catalog migration note

If you previously used the **`wittprojects`** catalog (or `va_claims_ai`), migrate or recreate objects under **`bdr_labs`** (default Unity Catalog for this workspace). The FastAPI app reads **`DATABRICKS_UC_CATALOG`** and **`DATABRICKS_UC_SCHEMA`** (defaults: `bdr_labs` / `vba_claims_agent`).

---

## Tables (14 materialized views)

All 14 are Delta `MATERIALIZED_VIEW` objects in `bdr_labs.vba_claims_agent`, refreshed manually (per `DESCRIBE TABLE EXTENDED`: `Refresh Schedule: MANUAL`). All 14 fall inside the same static **2024-01-01 to 2024-11-23** window — checked per-table, not assumed; see date ranges below. **This is a point-in-time snapshot, not a live feed.**

### `claims` — 120 rows
Gold table. DESCRIBE EXTENDED comment: *"Gold claims for VA Claims Dashboard + PACT adjudication API"*. Date range (`date_submitted`): 2024-01-01 to 2024-11-23.

| Column | Type |
|---|---|
| claim_id | string |
| veteran_name | string |
| date_submitted | date |
| claimed_condition | string |
| current_status | string |
| status | string |
| priority_level | string |
| fraud_score | double |
| fraud_reason | string |
| compliance_score | double |
| compliance_update | string |
| ai_summary | string |
| is_pact_act_eligible | **boolean** |
| exposure_type | string |
| decision_time_days | int |
| presumptive_match | **boolean** |
| priority_reason | string |
| veteran_id | string |

Confirmed `current_status` vocabulary (full `GROUP BY` over the table): `PENDING`, `DECISION_READY`, `REVIEW_REQUIRED`, `AWAITING_EVIDENCE`, `APPROVED`. **No `ACTIVE`, `DENIED`, or `DELAYED` — do not assume these values exist.**

### `gold_adjudication_reports` — 120 rows
**Confirmed literal alias of `claims`** — identical column set, and DESCRIBE EXTENDED comment states outright: *"Alias of claims for analytics / legacy SQL examples"* (same pipeline ID as `claims`). Not a distinct report shape; don't expect it to diverge. Date range: 2024-01-01 to 2024-11-23.

### `gold_claims_timeseries` — 66 rows
Weekly aggregate. Date range (`week_start`): 2024-01-01 to 2024-11-18.

| Column | Type |
|---|---|
| week_start | timestamp |
| current_status | string |
| claim_count | bigint |
| pact_eligible_count | bigint |

### `claim_evidence` — 480 rows
Evidence tracking, 1:many child of `claims`. **Confirmed exhaustive clean join**: 480/480 rows join to `claims.claim_id`, covering all 120 distinct claims (exactly 4 evidence rows per claim, no orphans).

| Column | Type |
|---|---|
| claim_id | string |
| evidence_type | string |
| status | string |
| completeness_score | double |

### `claim_history` — 360 rows
Audit trail, 1:many child of `claims`. **Confirmed exhaustive clean join**: 360/360 rows join to `claims.claim_id`, covering all 120 distinct claims (exactly 3 history rows per claim, no orphans). Date range (`action_date`): 2024-01-01 09:00 to 2024-11-23 14:00.

| Column | Type |
|---|---|
| claim_id | string |
| action_date | string |
| action_type | string |
| performed_by | string |

### `bronze_cerner_claim_extract` — 120 rows
Raw Cerner EHR claim extract. **Confirmed `cerner_claim_id` joins 1:1, exhaustively, to `claims.claim_id`** (120/120) — this was assumed *not* to join earlier tonight based on column-name mismatch; that assumption was wrong and has been corrected here. Carries `facility_id`, clinical coding, and risk/quality scores not present on `claims`. Date range (`service_date`): 2024-01-01 to 2024-11-23 (matches `claims` exactly).

| Column | Type |
|---|---|
| cerner_claim_id | string |
| patient_mrn | string |
| patient_display_name | string |
| service_date | string |
| diagnosis_text | string |
| icd10_cm_code | string |
| claim_status | string |
| priority_cd | string |
| risk_score | double |
| quality_score | double |
| pact_flag | int |
| exposure_category | string |
| enterprise_mrn | string |
| facility_id | string |

### `bronze_ccda_manifest` — 60 rows
CCDA document manifest. **Confirmed join to `bronze_cerner_claim_extract.cerner_claim_id` via `linked_cerner_claim_id`, but only partial coverage**: 60/120 — half of claims have no linked CCDA document. Do not assume every claim has one. Date range (`effective_time`): 2024-01-01 to 2024-11-22.

| Column | Type |
|---|---|
| document_id | string |
| linked_cerner_claim_id | string |
| doc_type | string |
| repository_uri | string |
| effective_time | string |

### `bronze_vista_event` — 80 rows
VistA (legacy VA EHR) event log. **Confirmed: no `claim_id` or `cerner_claim_id` column exists at all** — keyed only by `dfn`/`icn` (a separate patient-identifier system, 60 distinct `dfn`, 80 distinct `icn`). **No confirmed relationship to `claims` — not partially missing, structurally absent.** `station_id` is the only facility-like field here and it is not reachable from any claim. Date range (`event_dt`): 2024-01-01 to 2024-10-20.

| Column | Type |
|---|---|
| vista_event_id | string |
| dfn | string |
| icn | string |
| event_dt | string |
| event_type | string |
| station_id | string |

### `bronze_fhir_bundle` — 100 rows
Raw FHIR bundle payloads.

| Column | Type |
|---|---|
| bundle_id | string |
| raw_json | string |

**UNVERIFIED**: whether/how `bundle_id` relates to `claims` or `cerner_claim_id` — not tested tonight (opaque JSON blob, no structured key to test against).

### `silver_dim_icd10` — 5 rows
ICD-10 code dimension. **Confirmed clean join** from `bronze_cerner_claim_extract.icd10_cm_code`: 120/120 extract rows join successfully. Only 4 of the 5 dimension codes are actually referenced by the extract data.

| Column | Type |
|---|---|
| icd10_code | string |
| description | string |
| code_system | string |

### `silver_dim_loinc` — 4 rows
LOINC code dimension. **Confirmed clean join** from `silver_observation_loinc.loinc_code`: 200/200 rows join successfully.

| Column | Type |
|---|---|
| loinc_num | string |
| long_common_name | string |
| class_type | string |

### `silver_observation_loinc` — 200 rows
LOINC-coded clinical observations, keyed by `patient_key`.

| Column | Type |
|---|---|
| observation_id | string |
| patient_key | string |
| loinc_code | string |
| value_text | string |
| effective_date | string |

**UNVERIFIED**: relationship of `patient_key` to `claims.veteran_id` or any claim — not tested tonight.

### `silver_dim_snomed` — 4 rows
SNOMED CT concept dimension.

| Column | Type |
|---|---|
| concept_id | string |
| term | string |
| namespace | string |

**UNVERIFIED**: no table checked tonight (`claims`, `gold_adjudication_reports`, `bronze_cerner_claim_extract`, `silver_observation_loinc`) carries an obvious SNOMED concept-id column to join against this — the consumer of this dimension was not identified.

### `silver_va_doc_chunk` — 3 rows
VA policy document RAG chunks, used by `suggest_adjudication_decision` for citations.

| Column | Type |
|---|---|
| chunk_id | string |
| title | string |
| section | string |
| source_url | string |
| topic_tags | string |
| body | string |

Note: `topic_tags` exists but is not currently selected by the consuming query in `claims_service.py`.

---

## Confirmed relationships

- `claims` and `gold_adjudication_reports` have **identical column sets** and `gold_adjudication_reports` is a **documented literal alias** of `claims` (DESCRIBE EXTENDED comment), not a separate report shape.
- `status` and `current_status` on `claims`/`gold_adjudication_reports` are **always identical in the current data** — this is a data coincidence, not an enforced constraint. Code has been standardized on `current_status`.
- Confirmed `current_status` vocabulary: `PENDING`, `DECISION_READY`, `REVIEW_REQUIRED`, `AWAITING_EVIDENCE`, `APPROVED`. **No `ACTIVE`, `DENIED`, or `DELAYED`** — guessing this vocabulary caused real bugs tonight (`get_metrics`, `get_critical_claims`).
- `presumptive_match` and `is_pact_act_eligible` are **BOOLEAN**, not INT — comparisons must use the bare column or `true`/`false`, **never `= 1`/`= 0`**. This broke `get_adjudicator_stats` and `get_pact_act_statistics` tonight with a `DATATYPE_MISMATCH.BINARY_OP_DIFF_TYPES` error (both now fixed); swept the whole file, these are the only two boolean columns present anywhere in the schema.
- `claim_evidence` and `claim_history` are **fully exhaustive** 1:many children of `claims` (4 and 3 rows per claim respectively, verified via join — no orphans, no claim missing children).
- `bronze_cerner_claim_extract.cerner_claim_id` **joins 1:1 and exhaustively to `claims.claim_id`** (120/120) — confirmed by an actual join test tonight, correcting an earlier assumption (based on column-name mismatch alone) that this table had no join path.
- `bronze_cerner_claim_extract.icd10_cm_code` → `silver_dim_icd10.icd10_code`: clean join (120/120).
- `silver_observation_loinc.loinc_code` → `silver_dim_loinc.loinc_num`: clean join (200/200).
- `bronze_ccda_manifest.linked_cerner_claim_id` → `bronze_cerner_claim_extract.cerner_claim_id`: joins, but **partial** coverage (60/120).

## Confirmed NON-relationships (do not assume these joins exist)

- **There is no `region` field anywhere in this schema.** `bronze_cerner_claim_extract.facility_id` is the closest thing — a bare facility identifier string, not a region grouping — and it **does** join cleanly to `claims` (see above), correcting an earlier claim tonight that no provider/facility field joined to claims at all.
- **There is no true delay-hours / timestamp-pair duration field anywhere in this schema.** The only duration-like field in the entire schema is `claims.decision_time_days` (day granularity), already used by `get_metrics` and `get_adjudicator_stats`.
- Net effect: the original "provider + region + delay_hours" concept behind `get_visibility_gaps`/`get_region_delays` has **no real backing table**. A facility-level, day-granularity proxy (`bronze_cerner_claim_extract.facility_id` joined to `claims.decision_time_days`) is technically buildable — the join is verified — but region and hour-granularity delay remain genuinely unavailable. Both methods currently return mock data only; see the comment in `claims_service.py` next to each.
- `bronze_vista_event` has **no `claim_id`/`cerner_claim_id` column at all** — `dfn`/`icn` are a separate patient-identifier system with no confirmed link to `claims`, `veteran_id`, or any other table checked tonight.
- `silver_dim_snomed` — no consuming table/column identified tonight (see UNVERIFIED note above).
- `silver_observation_loinc.patient_key` → `claims.veteran_id`/`claim_id` — UNVERIFIED, not tested.
- `bronze_fhir_bundle.raw_json` → anything else — UNVERIFIED, not tested (opaque blob).

## Known data quirks

- **Static 2024 snapshot, not a live feed** — confirmed individually for all 14 tables (all fall within 2024-01-01 to 2024-11-23), not assumed from `claims` alone. Any `CURRENT_DATE`-relative filter will silently return zero rows against real "today." Anchor recency windows to `MAX(date_submitted)` (or the table's own date column) instead. This caused 3 confirmed bugs tonight (`get_metrics`, `get_critical_claims`, `get_adjudicator_stats`), all now fixed.
- `presumptive_match`/`is_pact_act_eligible` boolean-vs-integer comparisons are an outright query failure (`DATATYPE_MISMATCH`), not a silent wrong-result — caught by the existing try/except and masked as fallback data until investigated. Two confirmed instances tonight, both fixed; swept for a third.

## Used by `claims_service.py`

| Table | Method(s) | Columns read |
|---|---|---|
| `claims` | `get_metrics` | `decision_time_days`, `current_status`, `veteran_id`, `claim_id`, `date_submitted` |
| `claims` | `get_critical_claims` | `claimed_condition`, `veteran_id`, `current_status`, `date_submitted` |
| `claims` | `get_adjudicator_stats` | `current_status`, `decision_time_days`, `presumptive_match`, `date_submitted` |
| `claims` | `get_pending_claims` | `claim_id`, `veteran_name`, `date_submitted`, `claimed_condition`, `current_status`, `priority_level`, `fraud_score`, `compliance_score` |
| `claims` | `get_high_priority_claims` | `claim_id`, `veteran_name`, `date_submitted`, `claimed_condition`, `priority_reason`, `fraud_score`, `fraud_reason`, `compliance_update`, `ai_summary`, `priority_level`, `compliance_score` |
| `claims` | `get_pact_act_statistics` | `is_pact_act_eligible`, `exposure_type` |
| `claims` | `get_claim_detail` | `claim_id`, `veteran_name`, `date_submitted`, `claimed_condition`, `current_status`, `priority_level`, `fraud_score`, `fraud_reason`, `compliance_score`, `compliance_update`, `ai_summary`, `is_pact_act_eligible`, `exposure_type` |
| `claims` | `suggest_adjudication_decision` | `fraud_score`, `compliance_score`, `claimed_condition`, `current_status`, `claim_id` |
| `claim_evidence` | `_get_claim_evidence` | `claim_id`, `evidence_type`, `status`, `completeness_score` |
| `claim_history` | `_get_claim_history` | `claim_id`, `action_date`, `action_type`, `performed_by` |
| `gold_claims_timeseries` | `get_claims_timeseries` | `week_start`, `current_status`, `claim_count`, `pact_eligible_count` |
| `silver_va_doc_chunk` | `suggest_adjudication_decision` | `chunk_id`, `title`, `section`, `source_url`, `body` |

`get_visibility_gaps` and `get_region_delays` read **no table** — mock data only (see "Confirmed NON-relationships" above).
