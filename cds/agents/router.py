"""Offline router: decides which specialist agents a question needs (PRD FR-1).

In bedrock mode the Claude supervisor makes this decision itself; this router is
the deterministic stand-in used offline and as the routing baseline in evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cds.tools.guidelines import normalize_procedure

PATIENT_ID = re.compile(r"\bP-\d{4}\b", re.I)
REPORT_HINT = re.compile(r"\b(findings|impression)\s*:", re.I)

GUIDELINE_WORDS = re.compile(
    r"\b(acr|guideline|guidelines|appropriate|appropriateness|imaging|image|x-?ray|radiograph\w*|cxr|ct|cta|mri|"
    r"pet|scan|radiology|protocol|order|surveillance|criteria)\b", re.I)
REPORT_WORDS = re.compile(r"\b(report)\b.*\b(validate|check|review|complete|missing|standard)|"
                          r"\b(validate|check|review)\b.*\breport\b", re.I)
PATIENT_WORDS = re.compile(r"\b(similar|cohort|comparable|patients like|like this patient|matching patients|"
                           r"find patients|look like)\b", re.I)
BILLING_WORDS = re.compile(
    r"\b(bill\w*|codes?|cpt|hcpcs|fees?|costs?|price|pricing|pay|covered|coverage|prior auth\w*|authori[sz]ation|"
    r"supplies|supply|reimburs\w*|limits?|claims?|dme|how much)\b|\$", re.I)
CARE_PLAN_WORDS = re.compile(r"\b(copd|emphysema|asthma|sleep apnea|cpap|osa|tracheostomy|trach)\b", re.I)


@dataclass
class Route:
    agents: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    patient_id: str | None = None
    report: bool = False
    chart_check: bool = False

    def add(self, agent: str, reason: str):
        if agent not in self.agents:
            self.agents.append(agent)
            self.reasons[agent] = reason


def route(question: str, patient_id: str | None = None, report_text: str | None = None) -> Route:
    q = question or ""
    r = Route()
    pid = patient_id or (PATIENT_ID.search(q).group(0).upper() if PATIENT_ID.search(q) else None)
    r.patient_id = pid
    has_proc = normalize_procedure(q) is not None
    if report_text or REPORT_HINT.search(q) or REPORT_WORDS.search(q):
        r.report = True
        r.add("guidelines", "radiology report validation")
    if PATIENT_WORDS.search(q):
        r.add("patients", "similar-patient search")
    if pid and has_proc and not PATIENT_WORDS.search(q):
        r.chart_check = True
        r.add("guidelines", "chart-to-guideline order check")
    if has_proc or GUIDELINE_WORDS.search(q):
        if not (BILLING_WORDS.search(q) and not has_proc and not re.search(r"acr|guideline|imaging", q, re.I)):
            r.add("guidelines", "imaging guideline question")
    if BILLING_WORDS.search(q):
        r.add("billing", "billing, coverage or supply question")
        if CARE_PLAN_WORDS.search(q) and re.search(r"\b(diagnos\w*|need|plan|newly|new)\b", q, re.I):
            r.add("guidelines", "clinical context for a new diagnosis")
    # Keep a stable order: guidelines, patients, billing
    order = ["guidelines", "patients", "billing"]
    r.agents.sort(key=order.index)
    return r
