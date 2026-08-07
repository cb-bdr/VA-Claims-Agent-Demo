# VA Claims Agent — Databricks Asset Bundle

This folder holds **bundle includes** referenced from the root [databricks.yml](../databricks.yml).

## Layout

| Path | Purpose |
|------|---------|
| [resources/pipelines.yml](resources/pipelines.yml) | SDP resource |
| [notebooks/dlt_va_claims.py](notebooks/dlt_va_claims.py) | Medallion SDP (bronze → silver → gold) |
| [genie/VA_CLAIMS_GENIE_SPACE.md](genie/VA_CLAIMS_GENIE_SPACE.md) | Genie space — how to update/recreate |
| [genie/va_claims_genie_space.json](genie/va_claims_genie_space.json) | Versioned Genie space definition (tables, instructions, sample questions) |
| [src/data_generation/generate_seed_csvs.py](src/data_generation/generate_seed_csvs.py) | Optional local CSV seeds (documentation aid) |

## Commands

```bash
cd ..   # repo root
uv run python scripts/validate_va_claims_sdp_notebook.py   # optional: static SDP checks
databricks bundle validate
databricks bundle deploy -t dev
databricks bundle run va_claims_medallion -t dev --validate-only   # optional: graph check in workspace
uv run python scripts/sync_genie_space.py update --space-id 01f1901389231e9381ed2dffb7166d6c --profile feoycs
```

Variables (`catalog`, `schema`) are defined in the root `databricks.yml`.
