# Databricks notebook source
# MAGIC %md
# MAGIC # Synthetic Data Load — `bdr_labs.va_claims_tc`
# MAGIC
# MAGIC FEOYCS 2026 T-C · Phase 1 critical path.
# MAGIC
# MAGIC Generation logic is identical to the local run — this notebook only
# MAGIC changes the writer. Do not fork the logic here; edit the `generator`
# MAGIC package so the local exit gate stays authoritative.
# MAGIC
# MAGIC **Run order:** exit gate must be OPEN before any table is written.

# COMMAND ----------
# MAGIC %pip install -q pandas pyarrow
# dbutils.library.restartPython()

# COMMAND ----------
import sys

# Point at the bundle-synced repo checkout
REPO_PATH = "/Workspace/Users/cbrock@bdrsolutionsllc.com/.bundle/va_claims_agent_demo/dev/files/va_claims_tc_synthetic_generator/synthetic"
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from generator.build import build, report          # noqa: E402
from generator.writers import write_spark          # noqa: E402

# COMMAND ----------
dbutils.widgets.text("seed", "20260908")
dbutils.widgets.text("veterans", "500")
dbutils.widgets.text("claims", "600")
dbutils.widgets.text("schema", "bdr_labs.va_claims_tc")

SEED = int(dbutils.widgets.get("seed"))
SCHEMA = dbutils.widgets.get("schema")

# COMMAND ----------
# MAGIC %md ## 1. Generate and run the Phase 1 exit gate

# COMMAND ----------
ds = build(
    seed=SEED,
    n_veterans=int(dbutils.widgets.get("veterans")),
    n_claims=int(dbutils.widgets.get("claims")),
)
print(report(ds))

if not ds.ok:
    raise RuntimeError(
        "Phase 1 exit gate CLOSED — refusing to write tables. "
        "Fix the generator before proceeding to agent build."
    )

# COMMAND ----------
# MAGIC %md ## 2. Write Delta tables to Unity Catalog

# COMMAND ----------
manifest = write_spark(ds.frames, schema=SCHEMA, spark=spark, overwrite=True)
for t, meta in manifest["tables"].items():
    print(f"{t:<26} {meta['rows']:>8,}  ->  {meta['target']}")

print(f"\nHero case for the end-to-end walk: {ds.hero_claim_id}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## 3. Restrict the oracle tables
# MAGIC
# MAGIC `fact_ground_truth` and `scenario_expectation` are the test oracle. If the
# MAGIC agent service principal can read them the demonstration is invalid — the
# MAGIC system could answer from ground truth rather than from evidence.
# MAGIC
# MAGIC Replace `<agent_sp>` with the agent principal, then verify with
# MAGIC `SHOW GRANTS`.

# COMMAND ----------
catalog, sch = SCHEMA.split(".", 1)
for tbl in ("fact_ground_truth", "scenario_expectation"):
    print(f"REVOKE ALL PRIVILEGES ON TABLE {catalog}.{sch}.{tbl} FROM `<agent_sp>`;")

# COMMAND ----------
# MAGIC %md ## 4. Hero case inspection

# COMMAND ----------
hero = ds.hero_claim_id
display(spark.sql(f"""
    SELECT d.doc_type, d.index_status, d.custodian, d.page_count
    FROM {SCHEMA}.document d
    WHERE d.claim_id = '{hero}'
    ORDER BY d.doc_type
"""))

# COMMAND ----------
display(spark.sql(f"""
    SELECT scenario_id, requirement, expected_verdict, expected_refusal_reason
    FROM {SCHEMA}.scenario_expectation
    WHERE claim_id = '{hero}'
"""))
