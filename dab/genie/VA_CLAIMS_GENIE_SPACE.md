# Genie space — VA Claims Agent Demo

Genie configuration is **workspace-specific** and not expressible in Asset Bundle YAML. The space definition
lives in [`va_claims_genie_space.json`](va_claims_genie_space.json) (versioned in git) and is pushed to the
workspace via the Genie REST API through [`scripts/sync_genie_space.py`](../../scripts/sync_genie_space.py),
rather than pasted by hand into the Genie UI.

Current deployed space (workspace `dbc-8661319a-9b70.cloud.databricks.com`):

- `space_id`: `01f1901389231e9381ed2dffb7166d6c`
- `title`: VA Claims Adjudication Assistant
- `warehouse_id`: `f55e003d2e50b597` (Serverless Starter Warehouse — the only SQL warehouse in this workspace)

## 1. Trusted data

Tables attached (all in `bdr_labs.vba_claims_agent`, per the verified schema in
[`VA_CLAIMS_AI_TABLES.md`](../../VA_CLAIMS_AI_TABLES.md)):

- `claims`, `gold_claims_timeseries` — core claim + weekly aggregate
- `claim_evidence`, `claim_history` — confirmed exhaustive 1:many children of `claims` (joined on `claim_id`)
- `silver_va_doc_chunk` — VA policy-document excerpts for citations

`silver_dim_icd10` / `silver_observation_loinc` are **not** attached: they only join through
`bronze_cerner_claim_extract`, which isn't part of this space, so they'd be orphaned lookup tables with no
path back to `claims`.

## 2. Space instructions

Grounded in the verified facts in `VA_CLAIMS_AI_TABLES.md` (not hand-written guesses) — see
`instructions.text_instructions` in [`va_claims_genie_space.json`](va_claims_genie_space.json) for the exact
text pushed to the space. Notably: `current_status` has only 5 confirmed values (no `DENIED`/`ACTIVE`/`DELAYED`),
`is_pact_act_eligible`/`presumptive_match` are BOOLEAN (never `= 1`/`= 0`), and the data is a static 2024
snapshot (never filter relative to today's date).

## 3. Updating the space

Edit `va_claims_genie_space.json`, then:

```bash
# ids for any *new* sample_questions / text_instructions / example_question_sqls entries
# must be unique 32-char lowercase hex, and each list must stay sorted by id/identifier
uv run python -c "import uuid; print(uuid.uuid4().hex)"

uv run python scripts/sync_genie_space.py update --space-id 01f1901389231e9381ed2dffb7166d6c --profile feoycs
```

To create a fresh space instead (e.g. in a different workspace):

```bash
uv run python scripts/sync_genie_space.py create --warehouse-id <warehouse-id> --profile <profile>
```

## 4. Link from the Databricks App

- `VITE_GENIE_SPACE_URL` (frontend build time) — dashboard's "open in new tab" link
- `DATABRICKS_GENIE_SPACE_ID` (backend runtime) — floating "Ask Genie" chat proxy

**Confirmed working URL** (verified by actually opening it in a browser — the Genie REST API's `get-space`
response has no URL field at all, and the API/CLI's own "spaces" terminology is misleading: the real browser
route is `/genie/rooms/{id}`, not `/genie/spaces/{id}` — the latter 404s):

```
DATABRICKS_GENIE_SPACE_ID=01f1901389231e9381ed2dffb7166d6c
VITE_GENIE_SPACE_URL=https://dbc-8661319a-9b70.cloud.databricks.com/genie/rooms/01f1901389231e9381ed2dffb7166d6c
```

Set both in `.env.local` (see [.env.example](../../.env.example)).
