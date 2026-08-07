"""
Orchestrator + Phase 1 exit-gate validator.

The exit gate for Phase 1 is: "stress-test scenarios are representable in
data." validate() turns that into 20 assertions. If it fails, agents do not
get built -- that is the whole point of putting the generator on the critical
path.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import pandas as pd

from . import config as C
from . import generate as G
from . import scenarios as S


@dataclass
class Dataset:
    frames: dict
    hero_claim_id: str
    seed: int
    checks: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c["passed"] for c in self.checks)


def build(seed: int = 20260908, n_veterans: int = 500, n_claims: int = 600) -> Dataset:
    rng = random.Random(seed)

    vets = G.gen_veterans(rng, n_veterans)
    claims = G.gen_claims(rng, vets, n_claims)
    ev_req = G.gen_evidence_requirements()
    docs = G.gen_documents(rng, claims)
    facts, truth = G.gen_document_facts(rng, docs, vets, claims)
    hardship = G.gen_hardship_evidence(rng, claims, vets, docs)
    policies = G.gen_policy_references(rng)
    comms = G.gen_communications(rng, claims)
    conflicts = G.gen_conflict_pairs(rng, docs, facts)

    docs, facts, truth, hardship, comms, conflicts, expectations, hero = S.inject(
        rng, vets, claims, docs, facts, truth, hardship, comms, conflicts, policies)

    frames = {
        "veteran": vets,
        "claim": claims,
        "evidence_requirement": ev_req,
        "document": docs,
        "document_fact": facts,
        "hardship_evidence": hardship,
        "policy_reference": policies,
        "communication": comms,
        "conflict_pair": conflicts,
        "fact_ground_truth": truth,
        "scenario_expectation": expectations,
    }
    ds = Dataset(frames=frames, hero_claim_id=hero, seed=seed)
    validate(ds)
    return ds


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def _flash_consistency(f) -> bool:
    """Every deterministic hardship row must be backed by a matching corporate
    flash (or age) on the veteran record. Catches injection that adds a
    hardship row without updating the veteran."""
    inv = {v: k for k, v in C.FLASH_TO_CATEGORY.items()}
    vets = f["veteran"].set_index("veteran_id")
    c2v = f["claim"].set_index("claim_id")["veteran_id"].to_dict()
    det = f["hardship_evidence"]
    det = det[det.is_deterministic_category]
    for r in det.itertuples():
        vid = c2v.get(r.claim_id)
        if vid is None or vid not in vets.index:
            return False
        row = vets.loc[vid]
        if r.category == "AGE_85_OR_OLDER":
            if int(row["age"]) < 85:
                return False
        else:
            if inv.get(r.category) not in list(row["corporate_flashes"]):
                return False
    return True


def validate(ds: Dataset) -> Dataset:
    f = ds.frames
    checks = ds.checks

    def chk(name, condition, detail=""):
        checks.append({"check": name, "passed": bool(condition), "detail": detail})

    docs, facts, comms = f["document"], f["document_fact"], f["communication"]
    exp, hard, pol, conf = (f["scenario_expectation"], f["hardship_evidence"],
                            f["policy_reference"], f["conflict_pair"])

    # --- referential integrity ---
    chk("claim.veteran_id FK valid",
        set(f["claim"].veteran_id) <= set(f["veteran"].veteran_id))
    chk("document.claim_id FK valid",
        set(docs.claim_id) <= set(f["claim"].claim_id))
    chk("document_fact.doc_id FK valid",
        set(facts.doc_id) <= set(docs.doc_id))
    chk("no duplicate doc_id", docs.doc_id.is_unique)
    chk("no duplicate fact_id", facts.fact_id.is_unique)

    # --- the load-bearing field ---
    n_rni = int((docs.index_status == "received_not_indexed").sum())
    chk("index_status has all three states",
        set(docs.index_status) == set(C.INDEX_STATUS),
        f"received_not_indexed={n_rni}")
    chk("received_not_indexed present in volume", n_rni >= 20, f"n={n_rni}")

    # --- evidence coherence ---
    # A claim must never hold an absent/unindexed doc of type T alongside an
    # INDEXED doc of type T. That would mean requesting evidence already held.
    piv = (docs.assign(_ix=(docs.index_status == "indexed"))
                .groupby(["claim_id", "doc_type"])["_ix"].agg(["any", "all"]))
    incoherent = piv[(piv["any"]) & (~piv["all"])]
    chk("no claim holds both an indexed and a missing doc of the same type",
        len(incoherent) == 0, f"n={len(incoherent)}")
    chk("no orphaned facts after collision cleanup",
        set(facts.doc_id) <= set(docs.doc_id))
    chk("ground truth aligns 1:1 with facts",
        set(f["fact_ground_truth"].fact_id) == set(facts.fact_id))

    # --- provenance ---
    chk("every fact carries a page number",
        facts.page.notna().all() and (facts.page >= 1).all())
    chk("unindexed/absent docs yield no facts",
        len(set(facts.doc_id) & set(docs[docs.index_status != "indexed"].doc_id)) == 0)
    gt = facts.merge(f["fact_ground_truth"], on="fact_id")
    # Two DISTINCT failure modes. Checking only one lets the other go missing.
    hi_conf_wrong = gt[(gt.injected_error) & (gt.extraction_confidence > 0.85)]
    chk("confident-but-WRONG facts present (2023 OIG pattern)",
        len(hi_conf_wrong) >= 25, f"n={len(hi_conf_wrong)}")
    low_conf = gt[gt.error_class == "low_conf"]
    chk("low-confidence facts present (distinct from wrong-but-confident)",
        len(low_conf) >= 25, f"n={len(low_conf)}")
    chk("the two error classes are disjoint",
        len(set(hi_conf_wrong.fact_id) & set(low_conf.fact_id)) == 0)

    # --- hardship ---
    # NOTE: this assertion is deliberately equality, not subset. A subset check
    # (`<=`) is trivially true and will pass while categories are missing.
    present_cats = set(hard.category)
    chk("all 8 hardship categories present",
        present_cats == set(C.HARDSHIP_CATEGORIES),
        f"missing={sorted(set(C.HARDSHIP_CATEGORIES) - present_cats)}")
    thin = {c: int((hard.category == c).sum()) for c in C.HARDSHIP_CATEGORIES
            if int((hard.category == c).sum()) < C.MIN_ROWS_PER_HARDSHIP_CATEGORY}
    chk("every hardship category meets minimum row count", not thin, f"thin={thin}")
    chk("veteran flashes consistent with deterministic hardship rows",
        _flash_consistency(f), "")
    unver = hard[(~hard.verified) & (~hard.is_deterministic_category)]
    chk("unverified non-deterministic hardship present (S10 pattern)",
        len(unver) >= 20, f"n={len(unver)}")

    # --- policy supersession ---
    chk("superseded policy chain present",
        int(pol.superseded_by.notna().sum()) >= 2,
        f"n={int(pol.superseded_by.notna().sum())}")

    # --- conflicts ---
    chk("conflicts present and never auto-resolvable",
        len(conf) >= 10 and (~conf.auto_resolvable).all(), f"n={len(conf)}")

    # --- distress ---
    d_ct = comms.distress_band_truth.notna().sum()
    chk("distress signals present across all bands",
        set(comms.distress_band_truth.dropna()) == {"HOUSING", "MEDICAL", "FINANCIAL", "EMOTIONAL"},
        f"n={int(d_ct)}")
    chk("every distress message has a named escalation route",
        comms[comms.distress_band_truth.notna()].expected_route.notna().all())

    # --- scenarios ---
    present = set(exp.scenario_id)
    chk("all 12 scenarios represented",
        present == set(S.SCENARIO_CATALOG),
        f"missing={sorted(set(S.SCENARIO_CATALOG) - present)}")
    for reason in ("C1_ALLOWLIST", "C2_DETERMINISTIC_ABSENCE", "C3_UNAMBIGUOUS_CUSTODIAN"):
        chk(f"refusal reason {reason} exercised",
            reason in set(exp.expected_refusal_reason.dropna()))
    chk("L3 permit and refuse both exercised",
        {"permit", "refuse"} <= set(exp.expected_verdict.dropna()))

    # --- hero case ---
    hero_exp = exp[exp.is_hero_case]
    chk("hero case has >=6 expectations", len(hero_exp) >= 6, f"n={len(hero_exp)}")
    chk("hero case contains both a refuse and a permit",
        {"permit", "refuse"} <= set(hero_exp.expected_verdict.dropna()))
    hero_docs = docs[docs.claim_id == ds.hero_claim_id]
    chk("hero case has an unindexed allowlisted doc",
        len(hero_docs[(hero_docs.index_status == "received_not_indexed") &
                      (hero_docs.doc_type.isin(C.L3_ALLOWLIST))]) >= 1)
    chk("hero case has a distress message",
        comms[(comms.claim_id == ds.hero_claim_id) &
              (comms.distress_band_truth.notna())].shape[0] >= 1)

    return ds


def report(ds: Dataset) -> str:
    lines = []
    lines.append("=" * 74)
    lines.append("PHASE 1 EXIT GATE -- 'stress-test scenarios are representable in data'")
    lines.append("=" * 74)
    lines.append(f"seed={ds.seed}   hero_claim_id={ds.hero_claim_id}")
    lines.append("")
    lines.append("TABLE ROW COUNTS")
    for name, df in ds.frames.items():
        lines.append(f"  {name:<24} {len(df):>8,}")
    lines.append("")
    lines.append("CHECKS")
    for c in ds.checks:
        mark = "PASS" if c["passed"] else "FAIL"
        detail = f"   [{c['detail']}]" if c["detail"] else ""
        lines.append(f"  [{mark}] {c['check']}{detail}")
    n_pass = sum(c["passed"] for c in ds.checks)
    lines.append("")
    lines.append(f"RESULT: {n_pass}/{len(ds.checks)} checks passed"
                 f"  ->  GATE {'OPEN' if ds.ok else 'CLOSED'}")
    lines.append("=" * 74)
    return "\n".join(lines)
