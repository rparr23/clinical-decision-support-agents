"""Chart-to-guideline check (PRD FR-8): does a planned imaging order fit the ACR criteria and this patient's chart?"""

from __future__ import annotations

from typing import Any

from cds import trace
from cds.knowledge import data
from cds.tools import guidelines

VERDICTS = {
    "Usually Appropriate": "consistent",
    "May Be Appropriate": "review",
    "Usually Not Appropriate": "not supported",
}


def infer_scenario(patient, setting: str | None) -> tuple[str | None, list[str]]:
    """Pick the ACR routine-imaging variant from the chart. Returns (scenario, reasons)."""
    reasons = []
    setting = setting or patient.setting
    chronic = patient.chronic_cardiopulmonary
    if patient.symptoms:
        syms = ", ".join(f"{s.display} ({s.icd10})" for s in patient.symptoms)
        reasons.append(f"Active symptoms on the chart: {syms}.")
        return None, reasons
    if chronic:
        reasons.append("Chronic cardiopulmonary disease on the problem list: "
                       + ", ".join(f"{c.display} ({c.icd10})" for c in chronic) + ".")
    else:
        reasons.append("No chronic cardiopulmonary disease on the problem list.")
    if setting == "admission":
        return ("admission", reasons) if not chronic else ("surveillance", reasons + [
            "Admission without new symptoms in a patient with chronic disease is assessed as surveillance imaging."])
    if setting == "preop":
        return ("preop_chronic" if chronic else "preop"), reasons
    if setting in ("followup", "surveillance", "wellness"):
        if chronic:
            return "surveillance", reasons
        reasons.append("Routine imaging outside admission or surgery has no ACR variant for patients without chronic disease.")
        return None, reasons
    return None, reasons + [f"Encounter setting '{setting}' is not covered by the routine chest imaging topic."]


def check_order_against_chart(patient_id: str, order: str, setting: str = "") -> dict[str, Any]:
    """Check a planned chest imaging order for a synthetic patient against ACR routine chest imaging criteria."""
    with trace.span("tool", "check_order_against_chart", f"{patient_id}: {order}"):
        p = data.patients().get((patient_id or "").upper())
        if p is None:
            return {"found": False, "reason": f"No synthetic patient with id {patient_id}"}
        chart_cid = trace.current().cite("Synthetic FHIR R4 records", f"Patient {p.id}", p.text())
        proc = guidelines.normalize_procedure(order)
        scenario, reasons = infer_scenario(p, setting or None)
        notes = []
        if p.cardiac_device:
            notes.append(f"{p.cardiac_device[0].display} ({p.cardiac_device[0].icd10}) on the chart: ACR notes "
                         "preprocedural radiography can identify cardiac device type and location.")
        if p.transplant_risk:
            notes.append("Liver disease on the chart: ACR notes transplant candidates have higher rates of "
                         "intrathoracic disease.")
        base = {"found": True, "patient_id": p.id, "patient": p.text(), "order": order, "procedure": proc,
                "chart_citation": chart_cid, "reasons": reasons, "notes": notes}
        if proc is None:
            return base | {"verdict": "not assessable", "explanation": "The order is not a chest imaging procedure "
                           "rated in ACR Routine Chest Imaging."}
        if scenario is None:
            scope = data.guidelines()["passages"][0]
            cid = trace.current().cite(data.guidelines()["source"]["title"], f"{scope['section']}, p. {scope['page']}",
                                       scope["text"], data.guidelines()["source"]["url"])
            return base | {"verdict": "outside routine imaging", "guideline_citation": cid,
                           "explanation": "The routine chest imaging criteria do not apply: they exclude imaging for "
                                          "acute illness or a specific clinical question. Use the ACR topic for the "
                                          "presenting problem instead."}
        rating = guidelines.check_imaging_appropriateness(proc, scenario)
        return base | {"verdict": VERDICTS.get(rating.get("category"), "not assessable"), "scenario": scenario,
                       "variant": rating.get("variant"), "category": rating.get("category"),
                       "relative_radiation_level": rating.get("relative_radiation_level"),
                       "alternatives_rated_higher": rating.get("alternatives_rated_higher", []),
                       "guideline_citation": rating.get("citation"), "explanation": rating.get("summary", "")}
