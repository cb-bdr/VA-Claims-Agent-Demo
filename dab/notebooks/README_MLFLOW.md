# MLflow / Unity Catalog model registration (optional)

This repo does **not** auto-register a fine-tuned model: VA environments vary. Use this outline after you train or wrap a foundation-model prompt:

1. In a Databricks notebook, train or package your prompt + retrieval config.
2. `mlflow.set_registry_uri("databricks-uc")` and log the artifact.
3. Register with `mlflow.register_model(model_uri, name)` under a UC model name, e.g. `bdr_labs.adjudication_suggest`.
4. Deploy a **Model Serving** endpoint; set `DATABRICKS_ADJUDICATION_SUGGEST_URL` to its `/invocations` URL.

Do **not** depend on Inference Tables for this demo path.
