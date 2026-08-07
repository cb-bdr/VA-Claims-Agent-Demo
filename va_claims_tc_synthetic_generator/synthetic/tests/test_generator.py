"""Regression tests. Run: python3 -m pytest tests/ -q"""
import hashlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from generator.build import build
from generator import config as C
from generator.scenarios import SCENARIO_CATALOG

DS = build(seed=20260908, n_veterans=500, n_claims=600)


def test_exit_gate_open():
    failed = [c["check"] for c in DS.checks if not c["passed"]]
    assert not failed, f"exit gate closed: {failed}"


def test_determinism_same_seed():
    a = build(seed=777, n_veterans=120, n_claims=150)
    b = build(seed=777, n_veterans=120, n_claims=150)
    for name in a.frames:
        ha = hashlib.sha256(
            a.frames[name].astype(str).to_csv(index=False).encode()).hexdigest()
        hb = hashlib.sha256(
            b.frames[name].astype(str).to_csv(index=False).encode()).hexdigest()
        assert ha == hb, f"{name} not reproducible"
    assert a.hero_claim_id == b.hero_claim_id


def test_different_seed_differs():
    a = build(seed=1, n_veterans=120, n_claims=150)
    b = build(seed=2, n_veterans=120, n_claims=150)
    assert not a.frames["claim"].equals(b.frames["claim"])


def test_all_scenarios_have_expectations():
    exp = DS.frames["scenario_expectation"]
    assert set(exp.scenario_id) == set(SCENARIO_CATALOG)


def test_l3_allowlist_semantics():
    """C1 must be derivable from config alone -- not from model inference."""
    assert set(C.L3_ALLOWLIST) == {"STR", "VAMC_TREATMENT", "DD214"}
    for dt in C.L3_ALLOWLIST:
        assert C.DOC_TYPES[dt][1] is True, f"{dt} allowlisted but custodian ambiguous"


def test_c2_refusal_is_representable():
    """The primary demo moment: an allowlisted doc that reads as received but
    not indexed. If this is absent the demonstration has no climax."""
    d = DS.frames["document"]
    hits = d[(d.index_status == "received_not_indexed") &
             (d.doc_type.isin(C.L3_ALLOWLIST))]
    assert len(hits) >= 10, f"only {len(hits)} C2-refusal candidates"


def test_no_facts_from_unindexed_docs():
    d, f = DS.frames["document"], DS.frames["document_fact"]
    bad = set(f.doc_id) & set(d[d.index_status != "indexed"].doc_id)
    assert not bad, f"facts extracted from non-indexed docs: {list(bad)[:5]}"


def test_every_fact_has_provenance():
    f = DS.frames["document_fact"]
    assert f.page.notna().all() and (f.page >= 1).all()
    assert f.extractor_version.notna().all()
    assert f.doc_id.notna().all()


def test_ground_truth_is_separable():
    """Oracle tables must be droppable without breaking the operational set."""
    oracle = {"fact_ground_truth", "scenario_expectation"}
    ops = {k: v for k, v in DS.frames.items() if k not in oracle}
    assert "distress_band_truth" in DS.frames["communication"].columns
    for name, df in ops.items():
        assert len(df) > 0, name


def test_hardship_never_auto_applied_flag_present():
    """Deterministic categories may be DETECTED; the schema must still record
    verification separately so nothing implies auto-application."""
    h = DS.frames["hardship_evidence"]
    assert "verified" in h.columns and "is_deterministic_category" in h.columns
    nd = h[~h.is_deterministic_category]
    assert (~nd.verified).any(), "no unverified non-deterministic hardship"


def test_distress_never_lacks_route():
    c = DS.frames["communication"]
    d = c[c.distress_band_truth.notna()]
    assert len(d) > 0
    assert d.expected_route.notna().all()
    assert d.expected_route.map(lambda r: r.isupper()).all()


def test_superseded_policy_chain_resolves():
    p = DS.frames["policy_reference"]
    sup = p[p.superseded_by.notna()]
    assert len(sup) >= 2
    assert set(sup.superseded_by) <= set(p.policy_id)
    assert (~sup.is_current).all()


def test_conflicts_never_auto_resolvable():
    c = DS.frames["conflict_pair"]
    assert len(c) > 0 and (~c.auto_resolvable).all()


def test_hero_case_is_rich_enough():
    exp = DS.frames["scenario_expectation"]
    hero = exp[exp.is_hero_case]
    sensors = set(hero.expected_sensor.dropna())
    assert {"MISSING_DOCUMENT", "CONFLICT", "HUMAN_DISTRESS", "RISK"} <= sensors
    assert {"permit", "refuse"} <= set(hero.expected_verdict.dropna())
