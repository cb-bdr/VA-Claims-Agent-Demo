#!/usr/bin/env python3
"""Fail loudly if the GATED oracle tables are readable by anyone unexpected.

bdr_labs.va_claims_tc.fact_ground_truth and .scenario_expectation are the test
oracle for the L3 authority demonstration. If an agent (or its service
principal) can read them, the demonstration is invalid -- the system could
answer from ground truth instead of from evidence.

Run this:
  - Before granting ANY new principal access to bdr_labs.va_claims_tc.
  - Immediately after creating an agent service principal, before granting it
    anything on this schema.
  - As a pre-flight step in whatever job/script eventually provisions an
    agent's UC grants -- wire a call to this script in before that grant step,
    not after, and have it block the grant on a nonzero exit code.

It checks CATALOG, SCHEMA, and both oracle TABLE grants (a broad SELECT at the
catalog or schema level cascades down to these tables even with no table-level
grant, so all three levels must be checked, not just the tables themselves).

Usage:
    uv run python scripts/verify_oracle_lockout.py --profile feoycs
    uv run python scripts/verify_oracle_lockout.py --profile feoycs --allow some.other@identity
Exit code 0 = locked down. Exit code 1 = violation found (or the check itself failed).
"""
import argparse
import sys

from databricks.sdk import WorkspaceClient

CATALOG = "bdr_labs"
SCHEMA = "va_claims_tc"
ORACLE_TABLES = ["fact_ground_truth", "scenario_expectation"]

# Privileges that grant actual row access, directly or by implication.
# BROWSE/USE CATALOG/USE SCHEMA/CREATE SCHEMA are metadata/navigation only and
# do not expose row data on their own -- excluded on purpose.
READ_CAPABLE_PRIVILEGES = {"SELECT", "MODIFY", "ALL PRIVILEGES", "ALL_PRIVILEGES", "OWN"}


def show_grants(w: WorkspaceClient, warehouse_id: str, object_type: str, object_name: str):
    sql = f"SHOW GRANTS ON {object_type} {object_name}"
    resp = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=sql, wait_timeout="30s")
    if resp.status.error:
        raise RuntimeError(f"SHOW GRANTS ON {object_type} {object_name} failed: {resp.status.error}")
    cols = [c.name for c in resp.manifest.schema.columns] if resp.manifest and resp.manifest.schema else []
    rows = (resp.result.data_array or []) if resp.result else []
    idx = {c: i for i, c in enumerate(cols)}
    return [
        {
            "principal": r[idx["Principal"]],
            "action_type": r[idx["ActionType"]],
            "object_type": object_type,
            "object_name": object_name,
        }
        for r in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default=None, help="Databricks CLI profile (defaults to unified-auth resolution)")
    parser.add_argument("--warehouse-id", default="f55e003d2e50b597")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Principal (user email, group name, or SP client_id) explicitly permitted to read "
             "the oracle tables. Repeatable. The caller's own identity is always allowed. "
             "In practice this should stay empty -- oracle tables should be readable by no one "
             "but the human validating the corpus.",
    )
    args = parser.parse_args()

    w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    me = w.current_user.me()
    allowed = {a for a in args.allow} | {me.user_name}

    checks = [
        ("CATALOG", CATALOG),
        ("SCHEMA", f"{CATALOG}.{SCHEMA}"),
    ] + [("TABLE", f"{CATALOG}.{SCHEMA}.{t}") for t in ORACLE_TABLES]

    all_grants = []
    for object_type, object_name in checks:
        all_grants.extend(show_grants(w, args.warehouse_id, object_type, object_name))

    violations = [g for g in all_grants if g["principal"] not in allowed and g["action_type"] in READ_CAPABLE_PRIVILEGES]
    informational = [g for g in all_grants if g["principal"] not in allowed and g["action_type"] not in READ_CAPABLE_PRIVILEGES]

    print(f"Checked: {', '.join(f'{ot} {on}' for ot, on in checks)}")
    print(f"Allowed identities: {sorted(allowed)}")

    if informational:
        print("\nNon-read grants to other principals (not a violation, shown for awareness):")
        for g in informational:
            print(f"  - {g['principal']!r} has {g['action_type']} on {g['object_type']} {g['object_name']}")

    if violations:
        print("\n*** ORACLE LOCKOUT VIOLATION ***", file=sys.stderr)
        print(
            "The following grants let a principal other than an allowed identity read "
            "the GATED oracle tables, directly or via catalog/schema-level cascade:",
            file=sys.stderr,
        )
        for g in violations:
            print(f"  - {g['principal']!r} has {g['action_type']} on {g['object_type']} {g['object_name']}", file=sys.stderr)
        print(
            "\nDo NOT build or run any agent against bdr_labs.va_claims_tc until this is fixed.\n"
            "REVOKE the offending privilege(s), e.g.:\n"
            f"  REVOKE <privilege> ON <object> FROM `<principal>`;\n"
            "or, if the principal genuinely needs it (should be rare), re-run with --allow.",
            file=sys.stderr,
        )
        return 1

    print(
        "\nOK: fact_ground_truth and scenario_expectation are not readable by anyone "
        "outside the allowed identities. Safe to proceed with agent grants."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
