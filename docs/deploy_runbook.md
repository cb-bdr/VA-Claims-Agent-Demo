# Deploy runbook — DAB + Databricks App (VA Claims Agent Demo)

## Prerequisites

- Databricks CLI **0.265+** (`databricks --version`).
- Unity Catalog **CREATE CATALOG** / **USE CATALOG** rights (or use an existing catalog and override variables).
- **Databricks Apps** enabled for deploy target.
- Local: `uv`, Node 18+, `npm` or `bun` (see [setup.sh](../setup.sh)).

## 1. Configure environment

Copy [.env.example](../.env.example) to `.env.local` and set at least:

- `DATABRICKS_HOST`, `DATABRICKS_TOKEN`
- `DATABRICKS_APP_NAME`, `DBA_SOURCE_CODE_PATH`
- `DATABRICKS_UC_CATALOG`, `DATABRICKS_UC_SCHEMA` (defaults: `bdr_labs`, `vba_claims_agent`)

Optional:

- `DATABRICKS_SERVING_ENDPOINT_URL`, `DATABRICKS_ADJUDICATION_SUGGEST_URL`
- For Genie link in UI: set `VITE_GENIE_SPACE_URL` **before** `npm run build` / deploy (Vite embeds at build time).

## 2. Deploy the Asset Bundle (data plane)

### Verify locally (no Databricks credentials)

From the **repository root**, run the static checker on the SDP notebook (syntax, no legacy `dlt`, `spark.table` names resolve to defined datasets):

```bash
uv run python scripts/validate_va_claims_sdp_notebook.py
```

### Deploy

From the **repository root**:

```bash
databricks bundle validate
databricks bundle deploy -t dev
```

### Verify in your workspace (high confidence before a full update)

After deploy, ask Databricks to **validate the pipeline graph** (planning / analysis) without requiring a belief that everything will succeed at runtime—it catches missing tables, bad references, and many Python analysis errors:

```bash
databricks bundle run va_claims_medallion -t dev --validate-only
```

Wait until it finishes successfully, then start a normal update from the UI or:

```bash
databricks bundle run va_claims_medallion -t dev
```

Together: **local script + `bundle validate` + `bundle run … --validate-only`** is the strongest check you can automate without hand-waving; the last few percent is workspace-specific (UC grants, quotas, runtime).

This syncs bundle files and creates/updates **SDP** `va_claims_medallion_dev` (name may include target).

### First-time catalog

If `bdr_labs` does not exist, create it in Unity Catalog (SQL or UI), then run the pipeline:

```sql
CREATE CATALOG IF NOT EXISTS bdr_labs;
CREATE SCHEMA IF NOT EXISTS bdr_labs.vba_claims_agent;
```

Grants: give the SDP’s service principal **USE CATALOG**, **USE SCHEMA**, **CREATE TABLE**, **SELECT**, **MODIFY** as required.

### Run the pipeline

In **Databricks UI**: open **Workflows** / **Data Engineering**, select the `va_claims_medallion_*` **SDP**, then **Start**.

After success, verify:

```sql
SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.claims;
SELECT COUNT(*) FROM bdr_labs.vba_claims_agent.gold_claims_timeseries;
```

## 3. Configure Genie (optional)

Follow [dab/genie/VA_CLAIMS_GENIE_SPACE.md](../dab/genie/VA_CLAIMS_GENIE_SPACE.md).

For **embedded Genie** on the PACT adjudication dashboard, set **`VITE_GENIE_SPACE_URL`** at **build** time to your Genie space URL. Its hostname must match **`DATABRICKS_HOST`**. The UI calls **`GET /api/claims/genie/verify`** (workspace PAT) before showing an iframe; if the iframe stays blank (browser/workspace frame policy), use **Open Genie space (new tab)**.

## 4. Deploy the Databricks App (UI + API)

```bash
./deploy.sh --create   # first time only
./deploy.sh
```

Ensure the app’s environment (or `.databricks.env` synced with the app) includes the same `DATABRICKS_*` variables as `.env.local` where applicable. Set **`DATABRICKS_SQL_WAREHOUSE_ID`** if SQL for timeseries/doc chunks does not resolve a warehouse automatically.

### Databricks App: API returns **404 Not Found** for `/api/claims/...`

Some deployments forward paths **without** the `/api` prefix. This repo registers the claims router **twice** (`/api/claims/...` and `/claims/...`) and the React client **retries** `/claims/...` if the first request is 404. Redeploy the app after pulling the latest server + client build.

### Genie verify: **HTTP 404**

Use the **exact Genie space URL** from the browser address bar while the space is open (same hostname as `DATABRICKS_HOST`). Verification uses **HEAD**, then **GET** if HEAD is 404/405. If GET is still 404, the path is wrong or the space was deleted — fix `VITE_GENIE_SPACE_URL` and rebuild the client.

## 5. Smoke tests

```bash
curl -s "$HOST/api/claims/adjudication/timeseries" | head
curl -s -X POST "$HOST/api/claims/adjudication/suggest" \
  -H "Content-Type: application/json" \
  -d '{"claimId":"CERNER-100000"}'
```

Replace `HOST` with your app URL.

## Order summary

1. `databricks bundle deploy`
2. Start SDP (once catalog/schema exist)
3. Configure Genie + `VITE_GENIE_SPACE_URL` rebuild if needed
4. `./deploy.sh`

## Troubleshooting

### “You must use serverless compute in this workspace”

Some workspaces **do not allow** classic (cluster-backed) SDP pipelines. The bundle sets **`serverless: true`** on `va_claims_medallion` in [`dab/resources/pipelines.yml`](../dab/resources/pipelines.yml). If you still see this error, upgrade the Databricks CLI (`databricks --version`; use **0.265+**), pull the latest repo, and run `databricks bundle deploy -t dev` again. Do not add a `clusters:` block unless your admin allows provisioned compute for pipelines.

### `NO_TABLES_IN_PIPELINE` (no tables found)

On **Lakeflow / serverless SDP**, Python must use **`from pyspark import pipelines as dp`** with **`@dp.materialized_view`** (batch) or **`@dp.table`** (streaming), and reference other pipeline datasets with **`spark.table("dataset_name")`**. The legacy **`import dlt` / `@dlt.table` / `dlt.read`** module often does **not** register datasets in that runtime, which triggers this error. The demo notebook [`dab/notebooks/dlt_va_claims.py`](../dab/notebooks/dlt_va_claims.py) uses the `dp` API. See [Lakeflow SDP Python reference](https://docs.databricks.com/en/delta-live-tables/python-ref.html) and [What happened to `@dlt`?](https://docs.databricks.com/en/delta-live-tables/python-ref.html#what-happened-to-dlt).

**Notebook format:** Databricks `.py` notebooks must separate markdown from code with **`# COMMAND ----------`**. If `%md` and Python are not split, the Python (including all `@dp` definitions) may never run as code—the pipeline then reports no tables. The demo notebook includes that delimiter after the header markdown.

### `DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES`

Usually a **bad `.alias()` scope**: in PySpark, `a + b.cast(...).alias("x")` binds `.alias` to **`b` only**; the `+` then yields an auto-generated column name with `+`, `(`, etc., which Delta rejects. Wrap the full column expression in parentheses, then call `.alias("safe_name")` on the result.

## Optional job wrapper

You can add a **job** that runs the pipeline using `pipeline_task` referencing `${resources.pipelines.va_claims_medallion.id}` after the bundle defines stable IDs — template was omitted from the repo to avoid first-deploy circular references; add under `dab/resources/` if your CLI version supports it.
