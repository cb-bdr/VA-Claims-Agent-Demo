"""
Dual-mode output.

local  -> parquet + csv on disk. Runs anywhere, no Databricks dependency.
         This is why the generator can be built and validated BEFORE the
         Phase-0 workspace verifications complete.
spark  -> Delta tables in Unity Catalog under bdr_labs.va_claims_tc.
         Same frames, same names, no logic difference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config as C


def write_local(frames: dict[str, pd.DataFrame], outdir: str | Path) -> dict:
    out = Path(outdir)
    (out / "parquet").mkdir(parents=True, exist_ok=True)
    (out / "csv").mkdir(parents=True, exist_ok=True)

    manifest = {"schema": C.SCHEMA, "mode": "local", "tables": {}}
    for name, df in frames.items():
        d = df.copy()
        # list columns are not CSV-friendly; JSON-encode for the csv copy only
        csv_copy = d.copy()
        for col in csv_copy.columns:
            if csv_copy[col].map(lambda v: isinstance(v, (list, tuple))).any():
                csv_copy[col] = csv_copy[col].map(
                    lambda v: json.dumps(list(v)) if isinstance(v, (list, tuple)) else v)
        d.to_parquet(out / "parquet" / f"{name}.parquet", index=False)
        csv_copy.to_csv(out / "csv" / f"{name}.csv", index=False)
        manifest["tables"][name] = {"rows": int(len(d)), "columns": list(d.columns)}

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def write_spark(frames: dict[str, pd.DataFrame], schema: str = C.SCHEMA,
                spark=None, overwrite: bool = True) -> dict:
    """Write Delta tables to Unity Catalog. Call from a Databricks notebook or
    via Databricks Connect. Requires USE CATALOG / USE SCHEMA + CREATE TABLE."""
    if spark is None:                      # pragma: no cover
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()

    catalog, sch = schema.split(".", 1)
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{sch}")

    manifest = {"schema": schema, "mode": "spark", "tables": {}}
    mode = "overwrite" if overwrite else "append"
    for name, df in frames.items():
        sdf = spark.createDataFrame(df)
        target = f"{catalog}.{sch}.{name}"
        (sdf.write.format("delta").mode(mode)
            .option("overwriteSchema", "true").saveAsTable(target))
        manifest["tables"][name] = {"rows": int(len(df)), "target": target}

    # Ground-truth and oracle tables must never be readable by the agent
    # service principal. Tighten these immediately after load.
    for restricted in ("fact_ground_truth", "scenario_expectation"):
        manifest.setdefault("restricted", []).append(f"{catalog}.{sch}.{restricted}")

    return manifest
