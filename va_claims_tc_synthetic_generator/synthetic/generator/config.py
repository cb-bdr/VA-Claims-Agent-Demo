"""
Canonical vocabularies and the schema contract for bdr_labs.va_claims_tc.

This module is the single source of truth for field names and enumerations.
The agents read these names; the scenario-pack adapter (Aug 18) maps the real
Common Scenario Pack onto them. Change names HERE, nowhere else.
"""

from __future__ import annotations

SCHEMA = "bdr_labs.va_claims_tc"
RULE_VERSION = "ev-req-v1.0"
EXTRACTOR_VERSION = "ocr-extract-v0.9"

# ---------------------------------------------------------------------------
# Hardship categories -- mirror VA Form 20-10207 (Priority Processing Request)
# `deterministic` = establishable from structured data without human judgement.
# Only deterministic categories may ever be auto-detected; none may be
# auto-APPLIED (see never-automate declaration).
# ---------------------------------------------------------------------------
HARDSHIP_CATEGORIES = {
    "EXTREME_FINANCIAL_HARDSHIP": {"deterministic": False, "requires_evidence": True},
    "HOMELESS_OR_AT_RISK":        {"deterministic": False, "requires_evidence": True},
    "TERMINAL_ILLNESS":           {"deterministic": False, "requires_evidence": True},
    "SERIOUSLY_ILL_OR_INJURED":   {"deterministic": False, "requires_evidence": True},
    "FORMER_POW":                 {"deterministic": True,  "requires_evidence": False},
    "MEDAL_OF_HONOR":             {"deterministic": True,  "requires_evidence": False},
    "PURPLE_HEART":               {"deterministic": True,  "requires_evidence": False},
    "AGE_85_OR_OLDER":            {"deterministic": True,  "requires_evidence": False},
}

# Corporate flashes that evidence a deterministic hardship category
FLASH_TO_CATEGORY = {
    "POW":            "FORMER_POW",
    "MOH":            "MEDAL_OF_HONOR",
    "PURPLE_HEART":   "PURPLE_HEART",
    "HOMELESS":       "HOMELESS_OR_AT_RISK",
    "TERMINAL":       "TERMINAL_ILLNESS",
    "FIN_HARDSHIP":   "EXTREME_FINANCIAL_HARDSHIP",
    "SERIOUS_INJURY": "SERIOUSLY_ILL_OR_INJURED",
}

# Minimum rows required per hardship category for the dataset to be usable.
# Rare categories (MOH, POW) will not appear at realistic base rates in a
# 500-veteran sample, so coverage is guaranteed by injection rather than left
# to probability. Without this, sensor tests silently skip those branches.
MIN_ROWS_PER_HARDSHIP_CATEGORY = 3

# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
INDEX_STATUS = ["indexed", "received_not_indexed", "absent"]
INDEX_STATUS_WEIGHTS = [0.82, 0.06, 0.12]

# doc_type -> (custodian, custodian_is_unambiguous, on_l3_allowlist)
# `on_l3_allowlist` implements condition C1 of the bounded L3 lane.
# `custodian_is_unambiguous` implements condition C3.
DOC_TYPES = {
    "STR":                 ("NPRC",            True,  True),
    "VAMC_TREATMENT":      ("VAMC",            True,  True),
    "DD214":               ("NPRC",            True,  True),
    "PRIVATE_TREATMENT":   ("PRIVATE_PROVIDER", False, False),
    "CANDP_EXAM":          ("CONTRACT_EXAMINER", False, False),
    "LAY_STATEMENT":       ("CLAIMANT",        True,  False),
    "FINANCIAL_STATEMENT": ("CLAIMANT",        True,  False),
    "SHELTER_LETTER":      ("THIRD_PARTY",     False, False),
    "PHYSICIAN_STATEMENT": ("PRIVATE_PROVIDER", False, False),
    "FORM_20_10207":       ("CLAIMANT",        True,  False),
}

L3_ALLOWLIST = [d for d, (_, _, allow) in DOC_TYPES.items() if allow]

SOURCE_SYSTEMS = ["VBMS", "CAPRI", "eFolder_Upload", "Mail_Intake", "NPRC_Transfer"]

# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
CLAIM_TYPES = [
    "DISABILITY_COMPENSATION_INITIAL",
    "DISABILITY_COMPENSATION_INCREASE",
    "SUPPLEMENTAL_CLAIM",
    "HIGHER_LEVEL_REVIEW",
    "DIC",
    "PENSION",
]

# contention -> required doc types (deterministic evidence requirement rules)
CONTENTION_REQUIREMENTS = {
    "HYPERTENSION":       ["STR", "VAMC_TREATMENT"],
    "PTSD":               ["STR", "VAMC_TREATMENT", "CANDP_EXAM"],
    "TINNITUS":           ["STR", "CANDP_EXAM"],
    "KNEE_STRAIN":        ["STR", "VAMC_TREATMENT"],
    "DIABETES_TYPE_2":    ["STR", "VAMC_TREATMENT"],
    "SLEEP_APNEA":        ["VAMC_TREATMENT", "CANDP_EXAM"],
    "LUMBAR_STRAIN":      ["STR", "VAMC_TREATMENT"],
    "MIGRAINE":           ["VAMC_TREATMENT", "CANDP_EXAM"],
    "ISCHEMIC_HEART_DIS": ["STR", "VAMC_TREATMENT", "PRIVATE_TREATMENT"],
    "RESPIRATORY_TOXIC":  ["STR", "VAMC_TREATMENT", "CANDP_EXAM"],
}

CONTENTIONS = list(CONTENTION_REQUIREMENTS.keys())

STATIONS = {
    "316": ("Atlanta", "Southeast"),
    "362": ("Houston", "South Central"),
    "306": ("New York", "Northeast"),
    "343": ("Los Angeles", "Pacific"),
    "328": ("Chicago", "Midwest"),
    "339": ("Denver", "Mountain"),
}

BRANCHES = ["ARMY", "NAVY", "AIR_FORCE", "MARINE_CORPS", "COAST_GUARD"]

# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------
CHANNELS = ["SECURE_MESSAGE", "CALL_NOTE", "MAIL_SCAN", "VSO_INQUIRY"]

# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------
CONFLICT_TYPES = ["IDENTITY", "ELIGIBILITY", "SERVICE_DATES", "DEPENDENCY"]

# ---------------------------------------------------------------------------
# Sensors -- names must match sensor_reading.sensor_name exactly
# ---------------------------------------------------------------------------
SENSORS = [
    "ELIGIBILITY", "URGENCY", "RISK", "MISSING_DOCUMENT",
    "HUMAN_DISTRESS", "CONFIDENCE", "ESCALATION", "CONFLICT",
]

# L3 authority conditions C1-C5 (see architecture doc section 1)
L3_CONDITIONS = ["C1_ALLOWLIST", "C2_DETERMINISTIC_ABSENCE",
                 "C3_UNAMBIGUOUS_CUSTODIAN", "C4_NON_ADVERSE", "C5_DUTY_TO_ASSIST"]

# Table -> primary key, used by the validator
TABLES = {
    "veteran": "veteran_id",
    "claim": "claim_id",
    "document": "doc_id",
    "document_fact": "fact_id",
    "evidence_requirement": None,
    "hardship_evidence": None,
    "policy_reference": "policy_id",
    "communication": "msg_id",
    "conflict_pair": None,
    "fact_ground_truth": "fact_id",
    "scenario_expectation": None,
}
