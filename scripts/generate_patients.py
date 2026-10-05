"""Generate synthetic FHIR R4 patient bundles for the demo.

Every name, date and identifier here is invented. The output contains no real
patient data (no PHI). Run:

    python scripts/generate_patients.py --count 120

The first six patients are fixed demo cases used by the walkthrough and the
evaluation gold set; the rest are random but reproducible (seeded).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "cds" / "data" / "synthetic_patients.json"

CONDITIONS = {
    "copd": ("J44.9", "13645005", "Chronic obstructive pulmonary disease"),
    "asthma": ("J45.909", "195967001", "Asthma"),
    "heart_failure": ("I50.9", "84114007", "Heart failure"),
    "cad": ("I25.10", "53741008", "Coronary artery disease"),
    "ild": ("J84.9", "233703007", "Interstitial lung disease"),
    "diabetes": ("E11.9", "44054006", "Type 2 diabetes mellitus"),
    "hypertension": ("I10", "38341003", "Essential hypertension"),
    "osa": ("G47.33", "78275009", "Obstructive sleep apnea"),
    "hyperlipidemia": ("E78.5", "55822004", "Hyperlipidemia"),
    "ckd": ("N18.30", "433144002", "Chronic kidney disease stage 3"),
    "cirrhosis": ("K74.60", "19943007", "Cirrhosis of liver"),
    "pacemaker": ("Z95.0", "441509002", "Presence of cardiac pacemaker"),
    "cabg_history": ("Z95.1", "232717009", "History of coronary artery bypass graft"),
}
SYMPTOMS = {
    "cough": ("R05.9", "49727002", "Cough"),
    "dyspnea": ("R06.02", "267036007", "Shortness of breath"),
    "chest_pain": ("R07.9", "29857009", "Chest pain"),
    "fever": ("R50.9", "386661006", "Fever"),
}
MEDS = {
    "copd": ["tiotropium 18 MCG inhalation capsule", "albuterol 90 MCG/actuation inhaler"],
    "asthma": ["fluticasone 110 MCG/actuation inhaler", "albuterol 90 MCG/actuation inhaler"],
    "heart_failure": ["furosemide 40 MG oral tablet", "carvedilol 12.5 MG oral tablet"],
    "cad": ["atorvastatin 40 MG oral tablet", "aspirin 81 MG oral tablet"],
    "diabetes": ["metformin 500 MG oral tablet"],
    "hypertension": ["lisinopril 10 MG oral tablet"],
    "hyperlipidemia": ["atorvastatin 20 MG oral tablet"],
    "ild": ["pirfenidone 267 MG oral capsule"],
}
SETTINGS = {
    "admission": "Hospital admission",
    "preop": "Preoperative evaluation for noncardiothoracic surgery",
    "followup": "Outpatient follow-up, chronic disease",
    "wellness": "Annual wellness visit",
}
SURGERIES = ["total knee arthroplasty", "laparoscopic cholecystectomy", "hip arthroplasty",
             "inguinal hernia repair", "cataract extraction", "lumbar laminectomy"]
FIRST = {"female": ["Avery", "Brooke", "Celia", "Dana", "Elena", "Farah", "Greta", "Hana", "Iris", "June",
                    "Kira", "Lena", "Mara", "Nina", "Opal", "Priya", "Quinn", "Rosa", "Sana", "Tess"],
         "male": ["Aaron", "Bruno", "Calvin", "Dario", "Emil", "Felix", "Gavin", "Hugo", "Ivan", "Jonah",
                  "Kai", "Leon", "Milo", "Nolan", "Omar", "Pavel", "Rafael", "Silas", "Theo", "Victor"]}
LAST = ["Ashford", "Brightwater", "Calloway", "Delacroix", "Emberly", "Fairbanks", "Galloway", "Hollis",
        "Ingram", "Jansen", "Kestrel", "Lindqvist", "Marlowe", "Northcott", "Okafor", "Pemberton",
        "Quintero", "Rowan", "Sterling", "Thorne", "Underhill", "Vance", "Whitlock", "Yardley"]

FIXED = [
    # id, sex, age, conditions, symptoms, setting, spo2, smoker, note
    ("P-0001", "male", 45, ["hypertension"], [], "admission", 98, "never",
     "Admitted for elective observation after cellulitis of the leg; no cardiopulmonary complaints."),
    ("P-0002", "female", 68, ["copd", "hypertension"], [], "preop", 93, "former",
     "Scheduled for total knee arthroplasty."),
    ("P-0003", "male", 74, ["heart_failure", "cad", "pacemaker", "cabg_history"], [], "preop", 95, "former",
     "Scheduled for laparoscopic cholecystectomy."),
    ("P-0004", "female", 63, ["copd", "diabetes"], [], "followup", 92, "former",
     "Stable COPD, routine follow-up; no change in symptoms."),
    ("P-0005", "male", 58, ["diabetes", "hypertension"], ["dyspnea", "fever", "cough"], "admission", 89, "current",
     "Admitted with three days of fever, productive cough and shortness of breath."),
    ("P-0006", "female", 52, ["osa", "hypertension", "hyperlipidemia"], [], "wellness", 97, "never",
     "Annual visit; uses CPAP nightly."),
]


def _coding(system, code, display):
    return {"coding": [{"system": system, "code": code, "display": display}], "text": display}


def make_bundle(pid, sex, age, conds, symptoms, setting, spo2, smoker, note, rng):
    birth_year = 2026 - age
    birth = f"{birth_year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    first, last = rng.choice(FIRST[sex]), rng.choice(LAST)
    entries = [{"resource": {
        "resourceType": "Patient", "id": pid,
        "meta": {"tag": [{"system": "urn:cds:data", "code": "synthetic", "display": "Synthetic record, not a real person"}]},
        "name": [{"use": "official", "family": last, "given": [first]}],
        "gender": sex, "birthDate": birth}}]
    for key in conds:
        icd, snomed, display = CONDITIONS[key]
        entries.append({"resource": {
            "resourceType": "Condition", "id": f"{pid}-cond-{key}", "subject": {"reference": f"Patient/{pid}"},
            "clinicalStatus": _coding("http://terminology.hl7.org/CodeSystem/condition-clinical", "active", "Active"),
            "category": [_coding("http://terminology.hl7.org/CodeSystem/condition-category", "problem-list-item", "Problem list item")],
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": icd, "display": display},
                                {"system": "http://snomed.info/sct", "code": snomed, "display": display}], "text": display}}})
    for key in symptoms:
        icd, snomed, display = SYMPTOMS[key]
        entries.append({"resource": {
            "resourceType": "Condition", "id": f"{pid}-sym-{key}", "subject": {"reference": f"Patient/{pid}"},
            "clinicalStatus": _coding("http://terminology.hl7.org/CodeSystem/condition-clinical", "active", "Active"),
            "category": [_coding("http://terminology.hl7.org/CodeSystem/condition-category", "encounter-diagnosis", "Encounter diagnosis")],
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": icd, "display": display},
                                {"system": "http://snomed.info/sct", "code": snomed, "display": display}], "text": display}}})
    for key in conds:
        for i, med in enumerate(MEDS.get(key, [])):
            entries.append({"resource": {
                "resourceType": "MedicationRequest", "id": f"{pid}-med-{key}-{i}", "status": "active", "intent": "order",
                "subject": {"reference": f"Patient/{pid}"}, "medicationCodeableConcept": {"text": med}}})
    entries.append({"resource": {
        "resourceType": "Observation", "id": f"{pid}-spo2", "status": "final", "subject": {"reference": f"Patient/{pid}"},
        "code": _coding("http://loinc.org", "59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry"),
        "valueQuantity": {"value": spo2, "unit": "%"}}})
    entries.append({"resource": {
        "resourceType": "Observation", "id": f"{pid}-smoking", "status": "final", "subject": {"reference": f"Patient/{pid}"},
        "code": _coding("http://loinc.org", "72166-2", "Tobacco smoking status"),
        "valueCodeableConcept": {"text": {"never": "Never smoker", "former": "Former smoker", "current": "Current every day smoker"}[smoker]}}})
    reason = SETTINGS[setting]
    entries.append({"resource": {
        "resourceType": "Encounter", "id": f"{pid}-enc", "status": "in-progress",
        "class": {"code": "IMP" if setting == "admission" else "AMB"},
        "subject": {"reference": f"Patient/{pid}"},
        "type": [{"text": reason}],
        "extension": [{"url": "urn:cds:setting", "valueCode": setting}],
        "reasonCode": [{"text": note}]}})
    return {"resourceType": "Bundle", "id": f"bundle-{pid}", "type": "collection", "entry": entries}


def generate(count: int, seed: int = 20261005):
    rng = random.Random(seed)
    bundles = [make_bundle(*row, rng) for row in FIXED]
    chronic_pool = ["copd", "asthma", "heart_failure", "cad", "ild", "osa"]
    other_pool = ["diabetes", "hypertension", "hyperlipidemia", "ckd"]
    for n in range(len(FIXED) + 1, count + 1):
        sex = rng.choice(["female", "male"])
        age = rng.randint(22, 89)
        conds = rng.sample(other_pool, rng.randint(0, 2))
        if rng.random() < 0.55:
            conds += rng.sample(chronic_pool, rng.randint(1, 2))
        if "heart_failure" in conds and rng.random() < 0.3:
            conds.append("pacemaker")
        if "cad" in conds and rng.random() < 0.3:
            conds.append("cabg_history")
        if rng.random() < 0.05:
            conds.append("cirrhosis")
        symptoms = rng.sample(list(SYMPTOMS), rng.randint(1, 3)) if rng.random() < 0.2 else []
        setting = rng.choice(list(SETTINGS))
        chronic_lung = any(c in conds for c in ("copd", "ild", "heart_failure"))
        spo2 = rng.randint(87, 94) if chronic_lung else rng.randint(95, 99)
        smoker = rng.choice(["never", "former", "current"])
        note = {"admission": "Admitted for further evaluation.",
                "preop": f"Scheduled for {rng.choice(SURGERIES)}.",
                "followup": "Routine follow-up of chronic conditions.",
                "wellness": "Routine annual visit."}[setting]
        bundles.append(make_bundle(f"P-{n:04d}", sex, age, conds, symptoms, setting, spo2, smoker, note, rng))
    return bundles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    bundles = generate(args.count)
    args.out.write_text(json.dumps(bundles, indent=1))
    print(f"Wrote {len(bundles)} synthetic bundles to {args.out}")


if __name__ == "__main__":
    main()
