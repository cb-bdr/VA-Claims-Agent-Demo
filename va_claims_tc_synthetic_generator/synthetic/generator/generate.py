"""
Core synthetic data generation for bdr_labs.va_claims_tc.

Fully deterministic given a seed -- demo reproducibility is a risk-register
control, not a nicety. Same seed => byte-identical tables.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd

from . import config as C
from . import distress_corpus as DC

ASOF = date(2026, 8, 18)  # scenario "today" -- pack delivery date


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _d(rng, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max((end - start).days, 1)))


def _pick_weighted(rng, options, weights):
    return rng.choices(options, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# veterans
# ---------------------------------------------------------------------------
def gen_veterans(rng, n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        vid = f"V{100000 + i}"
        # age distribution skewed older; ~6% land in the 85+ deterministic band
        age = _pick_weighted(
            rng,
            [rng.randint(24, 39), rng.randint(40, 59), rng.randint(60, 74),
             rng.randint(75, 84), rng.randint(85, 96)],
            [0.16, 0.31, 0.29, 0.18, 0.06],
        )
        dob = date(ASOF.year - age, rng.randint(1, 12), rng.randint(1, 28))

        svc_start = date(dob.year + rng.randint(18, 24), rng.randint(1, 12), rng.randint(1, 28))
        svc_end = date(svc_start.year + rng.randint(2, 22), rng.randint(1, 12), rng.randint(1, 28))

        flashes = []
        if age >= 85:
            flashes.append("AGE_85")
        for flash, prob in (("POW", 0.010), ("MOH", 0.002), ("PURPLE_HEART", 0.055),
                            ("HOMELESS", 0.045), ("TERMINAL", 0.020),
                            ("FIN_HARDSHIP", 0.060), ("SERIOUS_INJURY", 0.030)):
            if rng.random() < prob:
                flashes.append(flash)

        rows.append({
            "veteran_id": vid,
            "dob": dob,
            "age": age,
            "branch": rng.choice(C.BRANCHES),
            "service_start": svc_start,
            "service_end": svc_end,
            "corporate_flashes": sorted(flashes),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------
def gen_claims(rng, vets: pd.DataFrame, n: int) -> pd.DataFrame:
    rows = []
    vids = vets["veteran_id"].tolist()
    for i in range(n):
        cid = f"C{500000 + i}"
        vid = rng.choice(vids)
        receipt = _d(rng, ASOF - timedelta(days=430), ASOF - timedelta(days=5))
        days_pending = (ASOF - receipt).days
        k = _pick_weighted(rng, [1, 2, 3, 4, 5], [0.22, 0.29, 0.24, 0.15, 0.10])
        rows.append({
            "claim_id": cid,
            "veteran_id": vid,
            "claim_type": _pick_weighted(
                rng, C.CLAIM_TYPES, [0.34, 0.26, 0.13, 0.09, 0.10, 0.08]),
            "receipt_date": receipt,
            "days_pending": days_pending,
            "is_backlog": days_pending > 125,
            "station_of_jurisdiction": rng.choice(list(C.STATIONS.keys())),
            "contentions": rng.sample(C.CONTENTIONS, k),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# evidence requirements (deterministic rules, versioned)
# ---------------------------------------------------------------------------
def gen_evidence_requirements() -> pd.DataFrame:
    rows = []
    for contention, docs in C.CONTENTION_REQUIREMENTS.items():
        for d in docs:
            rows.append({
                "contention": contention,
                "required_doc_type": d,
                "rule_version": C.RULE_VERSION,
                "is_mandatory": True,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# documents  (index_status is the load-bearing field for the L3 refusal)
# ---------------------------------------------------------------------------
def gen_documents(rng, claims: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = 0
    for c in claims.itertuples():
        required = set()
        for cont in c.contentions:
            required.update(C.CONTENTION_REQUIREMENTS[cont])
        # plus incidental documents
        extra = rng.sample(
            [d for d in C.DOC_TYPES if d not in required],
            k=min(rng.randint(0, 3), len(C.DOC_TYPES) - len(required)),
        )
        for dt in sorted(required) + extra:
            custodian, _unamb, _allow = C.DOC_TYPES[dt]
            status = _pick_weighted(rng, C.INDEX_STATUS, C.INDEX_STATUS_WEIGHTS)
            received = None if status == "absent" else _d(rng, c.receipt_date, ASOF)
            rows.append({
                "doc_id": f"D{900000 + n}",
                "claim_id": c.claim_id,
                "doc_type": dt,
                "custodian": custodian,
                "source_system": rng.choice(C.SOURCE_SYSTEMS),
                "received_date": received,
                "index_status": status,
                "page_count": 0 if status == "absent" else rng.randint(2, 240),
                "uri": None if status == "absent" else f"s3://synthetic-efolder/{c.claim_id}/D{900000+n}.pdf",
            })
            n += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# document facts + ground truth
# Models the 2023 OIG finding: extraction that looks confident but is wrong,
# and extraction that omits the reading a rater actually needed.
# ---------------------------------------------------------------------------
FACT_FIELDS = {
    "STR": ["service_start_date", "service_end_date", "branch", "in_service_complaint"],
    "VAMC_TREATMENT": ["encounter_date", "diagnosis_code", "bp_systolic", "bp_diastolic"],
    "DD214": ["service_start_date", "service_end_date", "character_of_service", "branch"],
    "CANDP_EXAM": ["exam_date", "examiner_opinion", "severity_rating"],
    "PRIVATE_TREATMENT": ["encounter_date", "diagnosis_code"],
    "PHYSICIAN_STATEMENT": ["opinion_date", "prognosis"],
    "FINANCIAL_STATEMENT": ["monthly_income", "monthly_expenses"],
    "SHELTER_LETTER": ["residency_start", "issuing_org"],
    "LAY_STATEMENT": ["statement_date"],
    "FORM_20_10207": ["requested_category", "signature_date"],
}


def gen_document_facts(rng, docs: pd.DataFrame, vets: pd.DataFrame,
                       claims: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    vet_by_claim = claims.set_index("claim_id")["veteran_id"].to_dict()
    vet_rows = vets.set_index("veteran_id").to_dict("index")

    facts, truth = [], []
    n = 0
    for d in docs.itertuples():
        if d.index_status != "indexed":
            continue  # unindexed/absent documents yield no extracted facts
        fields = FACT_FIELDS.get(d.doc_type, [])
        vid = vet_by_claim[d.claim_id]
        v = vet_rows[vid]
        for f in fields:
            # ~9% of facts get a deliberately wrong value at HIGH confidence
            # (the dangerous class), ~11% low-confidence, remainder clean.
            band = _pick_weighted(rng, ["clean", "low_conf", "wrong_high_conf"],
                                  [0.80, 0.11, 0.09])
            true_val, val = _fact_value(rng, f, v)
            injected = False
            if band == "wrong_high_conf":
                val = _corrupt(rng, f, val)
                injected = True
                conf = round(rng.uniform(0.88, 0.98), 3)
            elif band == "low_conf":
                conf = round(rng.uniform(0.31, 0.58), 3)
            else:
                conf = round(rng.uniform(0.80, 0.99), 3)

            fid = f"F{7000000 + n}"
            facts.append({
                "fact_id": fid,
                "doc_id": d.doc_id,
                "claim_id": d.claim_id,
                "page": rng.randint(1, max(d.page_count, 1)),
                "field": f,
                "value": str(val),
                "extraction_confidence": conf,
                "extractor_version": C.EXTRACTOR_VERSION,
            })
            truth.append({
                "fact_id": fid,
                "true_value": str(true_val),
                "injected_error": injected,
                "error_class": band if band != "clean" else None,
            })
            n += 1
    return pd.DataFrame(facts), pd.DataFrame(truth)


def _fact_value(rng, field: str, v: dict):
    if field == "service_start_date":
        val = v["service_start"]
    elif field == "service_end_date":
        val = v["service_end"]
    elif field == "branch":
        val = v["branch"]
    elif field in ("encounter_date", "exam_date", "opinion_date",
                   "statement_date", "signature_date", "residency_start"):
        val = _d(rng, date(2019, 1, 1), ASOF)
    elif field == "bp_systolic":
        val = rng.randint(118, 178)
    elif field == "bp_diastolic":
        val = rng.randint(68, 108)
    elif field == "diagnosis_code":
        val = rng.choice(["I10", "F43.10", "H93.11", "M25.561", "E11.9", "G47.33"])
    elif field == "character_of_service":
        val = _pick_weighted(rng, ["HONORABLE", "GENERAL", "OTH"], [0.88, 0.09, 0.03])
    elif field == "examiner_opinion":
        val = rng.choice(["AT_LEAST_AS_LIKELY_AS_NOT", "LESS_LIKELY_THAN_NOT", "UNABLE_TO_OPINE"])
    elif field == "severity_rating":
        val = rng.choice([0, 10, 20, 30, 50, 70])
    elif field == "prognosis":
        val = rng.choice(["GUARDED", "POOR", "STABLE", "TERMINAL"])
    elif field == "monthly_income":
        val = rng.randint(700, 4200)
    elif field == "monthly_expenses":
        val = rng.randint(900, 5100)
    elif field == "in_service_complaint":
        val = rng.choice([True, False])
    elif field == "issuing_org":
        val = rng.choice(["CITY_SHELTER", "VETERAN_OUTREACH", "COUNTY_SERVICES"])
    elif field == "requested_category":
        val = rng.choice(list(C.HARDSHIP_CATEGORIES.keys()))
    else:
        val = "UNKNOWN"
    return val, val


def _corrupt(rng, field: str, val):
    if isinstance(val, date):
        return val + timedelta(days=rng.choice([-1462, -397, 366, 1097]))
    if isinstance(val, bool):
        return not val
    if isinstance(val, int):
        return val + rng.choice([-42, -19, 23, 47])
    if isinstance(val, str):
        pool = ["I10", "F43.10", "HONORABLE", "OTH", "UNABLE_TO_OPINE", "STABLE", "ARMY", "NAVY"]
        alt = [p for p in pool if p != val]
        return rng.choice(alt)
    return val


# ---------------------------------------------------------------------------
# hardship evidence
# ---------------------------------------------------------------------------
def gen_hardship_evidence(rng, claims: pd.DataFrame, vets: pd.DataFrame,
                          docs: pd.DataFrame) -> pd.DataFrame:
    flashes = vets.set_index("veteran_id")["corporate_flashes"].to_dict()
    ages = vets.set_index("veteran_id")["age"].to_dict()
    docs_by_claim: dict[str, list] = {}
    for d in docs.itertuples():
        docs_by_claim.setdefault(d.claim_id, []).append(d)

    rows = []
    for c in claims.itertuples():
        fl = flashes[c.veteran_id]
        cats = set()
        if ages[c.veteran_id] >= 85:
            cats.add("AGE_85_OR_OLDER")
        for f in fl:
            if f in C.FLASH_TO_CATEGORY:
                cats.add(C.FLASH_TO_CATEGORY[f])

        for cat in cats:
            meta = C.HARDSHIP_CATEGORIES[cat]
            if meta["deterministic"]:
                verified, ev, asserted = True, None, "SYSTEM_FLASH"
            else:
                # non-deterministic categories are frequently asserted but
                # unverified -- the "flag, do not auto-prioritise" case
                supporting = [d for d in docs_by_claim.get(c.claim_id, [])
                              if d.doc_type in ("FINANCIAL_STATEMENT", "SHELTER_LETTER",
                                                "PHYSICIAN_STATEMENT", "FORM_20_10207")
                              and d.index_status == "indexed"]
                if supporting and rng.random() < 0.55:
                    verified, ev = True, rng.choice(supporting).doc_id
                else:
                    verified, ev = False, None
                asserted = rng.choice(["CLAIMANT", "VSO", "SYSTEM_FLASH"])
            rows.append({
                "claim_id": c.claim_id,
                "category": cat,
                "evidence_doc_id": ev,
                "asserted_by": asserted,
                "verified": verified,
                "is_deterministic_category": meta["deterministic"],
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# policy references (with supersession chains)
# ---------------------------------------------------------------------------
def gen_policy_references(rng) -> pd.DataFrame:
    base = [
        ("M21-1 X.i.1.A", "Priority Processing Programs"),
        ("M21-1 X.i.1.B", "Requests for Priority Processing"),
        ("M21-1 IV.ii.1.A", "Evidence Development Duties"),
        ("M21-1 IV.ii.1.C", "Federal Records Requests"),
        ("M21-1 V.iii.1.A", "Hardship Determinations"),
        ("38 CFR 3.159", "Duty to Assist"),
        ("38 USC 5103A", "Duty to Assist Claimants"),
        ("M21-1 IX.ii.2.B", "Terminal Illness Handling"),
    ]
    rows = []
    for i, (cite, title) in enumerate(base):
        pid = f"P{200 + i}"
        eff = date(2021 + (i % 4), rng.randint(1, 12), rng.randint(1, 28))
        rows.append({
            "policy_id": pid, "citation": cite, "title": title,
            "effective_date": eff, "superseded_by": None, "superseded_date": None,
            "is_current": True,
        })
    # supersede two of them -- creates the stress-test condition
    for idx, newsuffix in ((0, "A-1"), (4, "A-2")):
        old = rows[idx]
        npid = f"P{300 + idx}"
        sup_date = date(2026, rng.randint(1, 6), rng.randint(1, 28))
        rows.append({
            "policy_id": npid,
            "citation": old["citation"] + f" (rev {newsuffix})",
            "title": old["title"] + " (revised)",
            "effective_date": sup_date, "superseded_by": None,
            "superseded_date": None, "is_current": True,
        })
        old["superseded_by"] = npid
        old["superseded_date"] = sup_date
        old["is_current"] = False
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# communications
# ---------------------------------------------------------------------------
def gen_communications(rng, claims: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = 0
    for c in claims.itertuples():
        for _ in range(_pick_weighted(rng, [0, 1, 2, 3], [0.30, 0.40, 0.21, 0.09])):
            routine = rng.choice(DC.ROUTINE)
            # ~11% of messages carry a distress signal
            if rng.random() < 0.11:
                band = _pick_weighted(rng, ["HOUSING", "MEDICAL", "FINANCIAL", "EMOTIONAL"],
                                      [0.34, 0.30, 0.22, 0.14])
            else:
                band = None
            body, band = DC.compose(rng, routine, band)
            rows.append({
                "msg_id": f"M{400000 + n}",
                "claim_id": c.claim_id,
                "channel": rng.choice(C.CHANNELS),
                "received_at": _d(rng, c.receipt_date, ASOF),
                "body_text": body,
                "distress_band_truth": band,          # ground truth, not for agent use
                "expected_route": DC.ESCALATION_ROUTE.get(band) if band else None,
            })
            n += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# conflict pairs
# ---------------------------------------------------------------------------
def gen_conflict_pairs(rng, docs: pd.DataFrame, facts: pd.DataFrame,
                       rate: float = 0.06) -> pd.DataFrame:
    """Seed contradictions between two indexed docs on the same claim."""
    rows = []
    by_claim: dict[str, list] = {}
    for d in docs.itertuples():
        if d.index_status == "indexed":
            by_claim.setdefault(d.claim_id, []).append(d)

    for claim_id, dlist in by_claim.items():
        if len(dlist) < 2 or rng.random() > rate:
            continue
        a, b = rng.sample(dlist, 2)
        ctype = rng.choice(C.CONFLICT_TYPES)
        rows.append({
            "claim_id": claim_id,
            "doc_id_a": a.doc_id,
            "doc_id_b": b.doc_id,
            "conflict_type": ctype,
            "conflict_field": {"IDENTITY": "branch", "ELIGIBILITY": "character_of_service",
                               "SERVICE_DATES": "service_end_date",
                               "DEPENDENCY": "dependency_status"}[ctype],
            "auto_resolvable": False,   # never; must surface both sides
        })
    return pd.DataFrame(rows)
