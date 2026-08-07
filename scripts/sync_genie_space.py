"""
Create or update the VA Claims Genie space from dab/genie/va_claims_genie_space.json.

The Genie API stores a space's layout as a JSON string in the `serialized_space`
field (double-encoded). This script loads the human-editable nested JSON, wraps it
into that string, and shells out to the `databricks` CLI to create or update the
space, so the space definition stays versioned in git instead of hand-edited in
the Genie UI.

Usage:
    uv run python scripts/sync_genie_space.py create --warehouse-id <id> --profile feoycs
    uv run python scripts/sync_genie_space.py update --space-id <id> --profile feoycs
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SPACE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "dab" / "genie" / "va_claims_genie_space.json"
TITLE = "VA Claims Agent Demo — FEOYCS T-C"
DESCRIPTION = (
    "Ask natural language questions about synthetic VA claims: status, PACT Act "
    "eligibility, fraud/compliance scores, evidence completeness, and adjudication history."
)


def build_request_body(warehouse_id: str | None, space_id: str | None) -> dict:
    nested = json.loads(SPACE_CONFIG_PATH.read_text(encoding="utf-8"))
    body: dict = {
        "serialized_space": json.dumps(nested),
        "title": TITLE,
        "description": DESCRIPTION,
    }
    if warehouse_id:
        body["warehouse_id"] = warehouse_id
    if space_id:
        body["space_id"] = space_id
    return body


def run_cli(args: list[str]) -> None:
    result = subprocess.run(["databricks", *args], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "update"])
    parser.add_argument("--warehouse-id", help="Required for create")
    parser.add_argument("--space-id", help="Required for update")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    if args.action == "create" and not args.warehouse_id:
        parser.error("--warehouse-id is required for create")
    if args.action == "update" and not args.space_id:
        parser.error("--space-id is required for update")

    body = build_request_body(args.warehouse_id, args.space_id)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body, f)
        body_path = f.name

    cli_args = ["genie", f"{args.action}-space"]
    if args.action == "update":
        cli_args.append(args.space_id)
    cli_args += ["--json", f"@{body_path}", "-o", "json"]
    if args.profile:
        cli_args += ["--profile", args.profile]

    run_cli(cli_args)


if __name__ == "__main__":
    main()
