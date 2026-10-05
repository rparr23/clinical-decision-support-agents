"""Synthetic FHIR patient tools: chart lookup and similar-patient search."""

from __future__ import annotations

import re
from typing import Any

from cds import trace
from cds.knowledge import data, vectors
from cds.knowledge.fhir import PatientSummary

CONDITION_WORDS = {
    "copd": "Chronic obstructive pulmonary disease", "emphysema": "Chronic obstructive pulmonary disease",
    "asthma": "Asthma", "heart failure": "Heart failure", "chf": "Heart failure",
    "coronary": "Coronary artery disease", "cad": "Coronary artery disease",
    "interstitial": "Interstitial lung disease", "ild": "Interstitial lung disease",
    "diabetes": "Type 2 diabetes mellitus", "diabetic": "Type 2 diabetes mellitus",
    "hypertension": "Essential hypertension", "high blood pressure": "Essential hypertension",
    "sleep apnea": "Obstructive sleep apnea", "osa": "Obstructive sleep apnea",
    "hyperlipidemia": "Hyperlipidemia", "cholesterol": "Hyperlipidemia",
    "kidney": "Chronic kidney disease stage 3", "ckd": "Chronic kidney disease stage 3",
    "cirrhosis": "Cirrhosis of liver", "pacemaker": "Presence of cardiac pacemaker",
}


def _cite_patient(p: PatientSummary) -> str:
    return trace.current().cite("Synthetic FHIR R4 records", f"Patient {p.id}", p.text())


def get_patient_chart(patient_id: str) -> dict[str, Any]:
    """Return the summarized synthetic chart for one patient id (for example P-0002)."""
    with trace.span("tool", "get_patient_chart", patient_id):
        p = data.patients().get(patient_id.upper())
        if p is None:
            return {"found": False, "reason": f"No synthetic patient with id {patient_id}"}
        return {"found": True, "patient": p.as_dict(), "citation": _cite_patient(p)}


def parse_profile(query: str) -> dict[str, Any]:
    q = query.lower()
    age = re.search(r"(\d{1,3})[- ]?(year|yr|yo|y/o)", q)
    sex = "female" if re.search(r"\b(female|woman|women|she|her)\b", q) else (
        "male" if re.search(r"\b(male|man|men|he|his)\b", q) else None)
    conds = {v for k, v in CONDITION_WORDS.items() if re.search(r"\b" + re.escape(k), q)}
    return {"age": int(age.group(1)) if age else None, "sex": sex, "conditions": sorted(conds)}


def find_similar_patients(query: str = "", patient_id: str = "", k: int = 5) -> dict[str, Any]:
    """Find synthetic patients similar to a described profile or to an existing patient id."""
    with trace.span("tool", "find_similar_patients", patient_id or query):
        pts = data.patients()
        if patient_id and patient_id.upper() in pts:
            ref = pts[patient_id.upper()]
            profile = {"age": ref.age, "sex": ref.sex, "conditions": sorted(c.display for c in ref.conditions)}
        else:
            ref = None
            profile = parse_profile(query)
        target = {c.lower() for c in profile["conditions"]}
        scored = []
        if target or profile["age"] or profile["sex"]:
            for p in pts.values():
                if ref and p.id == ref.id:
                    continue
                pc = p.condition_keys()
                cond = len(target & pc) / len(target | pc) if (target or pc) else 0.0
                age = 1 - min(abs(p.age - profile["age"]), 30) / 30 if profile["age"] else 0.5
                sex = 1.0 if profile["sex"] and p.sex == profile["sex"] else (0.5 if not profile["sex"] else 0.0)
                score = 0.6 * cond + 0.25 * age + 0.15 * sex
                shared = sorted(c.display for c in p.conditions if c.display.lower() in target)
                scored.append((p, score, shared))
        else:
            for text, meta, score in vectors.search("patients", query, k * 2):
                p = pts.get(meta.get("id"))
                if p:
                    scored.append((p, score, []))
        scored.sort(key=lambda x: (-x[1], x[0].id))
        out = []
        for p, score, shared in scored[:k]:
            out.append({"id": p.id, "age": p.age, "sex": p.sex, "conditions": [c.display for c in p.conditions],
                        "shared_conditions": shared,
                        "similarity": round(score, 3), "citation": _cite_patient(p)})
        return {"profile": profile, "matches": out}
