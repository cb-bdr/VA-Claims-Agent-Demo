#!/usr/bin/env python3
"""CLI entry point for the synthetic data generator."""
import argparse, sys
from generator.build import build, report
from generator.writers import write_local

def main():
    p = argparse.ArgumentParser(description="Generate bdr_labs.va_claims_tc synthetic data")
    p.add_argument("--seed", type=int, default=20260908)
    p.add_argument("--veterans", type=int, default=500)
    p.add_argument("--claims", type=int, default=600)
    p.add_argument("--out", default="./out")
    p.add_argument("--strict", action="store_true", help="exit 1 if the exit gate fails")
    a = p.parse_args()

    ds = build(seed=a.seed, n_veterans=a.veterans, n_claims=a.claims)
    print(report(ds))
    m = write_local(ds.frames, a.out)
    print(f"\nWrote {len(m['tables'])} tables to {a.out}/ (parquet + csv)")
    if a.strict and not ds.ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
