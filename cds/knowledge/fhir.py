"""Turn a FHIR R4 bundle into a compact patient summary the agents can reason over."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Conditions that count as chronic cardiopulmonary disease for the ACR routine chest imaging variants
CHRONIC_CARDIOPULMONARY_ICD = ("J44", "J45", "I50", "I25", "J84", "Z95.1")
CARDIOTHORACIC_SURGERY_ICD = ("Z95.1",)
DEVICE_ICD = ("Z95.0",)
TRANSPLANT_RISK_ICD = ("K74",)


@dataclass
class Condition:
    icd10: str
    display: str
    category: str  # problem-list-item or encounter-diagnosis

    def as_dict(self) -> dict[str, str]:
        return {"icd10": self.icd10, "display": self.display, "category": self.category}


@dataclass
class PatientSummary:
    id: str
    name: str
    sex: str
    birth_date: str
    conditions: list[Condition] = field(default_factory=list)
    symptoms: list[Condition] = field(default_factory=list)
    medications: list[str] = field(default_factory=list)
    spo2: float | None = None
    smoking: str = ""
    setting: str = ""
    setting_label: str = ""
    encounter_note: str = ""

    @property
    def age(self) -> int:
        y, m, d = (int(x) for x in self.birth_date.split("-"))
        today = date.today()
        return today.year - y - ((today.month, today.day) < (m, d))

    def has(self, prefixes: tuple[str, ...]) -> list[Condition]:
        return [c for c in self.conditions if c.icd10.startswith(prefixes)]

    @property
    def chronic_cardiopulmonary(self) -> list[Condition]:
        return self.has(CHRONIC_CARDIOPULMONARY_ICD)

    @property
    def cardiac_device(self) -> list[Condition]:
        return self.has(DEVICE_ICD)

    @property
    def transplant_risk(self) -> list[Condition]:
        return self.has(TRANSPLANT_RISK_ICD)

    def condition_keys(self) -> set[str]:
        return {c.display.lower() for c in self.conditions}

    def text(self) -> str:
        conds = ", ".join(c.display for c in self.conditions) or "no chronic conditions"
        syms = ", ".join(c.display for c in self.symptoms)
        return (f"{self.age}-year-old {self.sex}. Conditions: {conds}."
                + (f" Current symptoms: {syms}." if syms else "")
                + f" Setting: {self.setting_label}. {self.encounter_note}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "sex": self.sex, "age": self.age, "birth_date": self.birth_date,
            "conditions": [c.as_dict() for c in self.conditions], "symptoms": [c.as_dict() for c in self.symptoms],
            "medications": self.medications, "spo2": self.spo2, "smoking": self.smoking,
            "setting": self.setting, "setting_label": self.setting_label, "encounter_note": self.encounter_note,
            "synthetic": True,
        }


def _icd(code_obj: dict) -> tuple[str, str]:
    for c in code_obj.get("coding", []):
        if "icd-10" in c.get("system", ""):
            return c["code"], c.get("display", code_obj.get("text", ""))
    return "", code_obj.get("text", "")


def parse_bundle(bundle: dict) -> PatientSummary:
    res = [e["resource"] for e in bundle.get("entry", [])]
    pat = next(r for r in res if r["resourceType"] == "Patient")
    nm = pat.get("name", [{}])[0]
    s = PatientSummary(
        id=pat["id"], name=" ".join(nm.get("given", []) + [nm.get("family", "")]).strip(),
        sex=pat.get("gender", "unknown"), birth_date=pat.get("birthDate", "1970-01-01"))
    for r in res:
        rt = r["resourceType"]
        if rt == "Condition":
            code, display = _icd(r.get("code", {}))
            cat = r.get("category", [{}])[0].get("coding", [{}])[0].get("code", "problem-list-item")
            (s.symptoms if cat == "encounter-diagnosis" else s.conditions).append(Condition(code, display, cat))
        elif rt == "MedicationRequest":
            s.medications.append(r.get("medicationCodeableConcept", {}).get("text", ""))
        elif rt == "Observation":
            loinc = r.get("code", {}).get("coding", [{}])[0].get("code")
            if loinc == "59408-5":
                s.spo2 = r.get("valueQuantity", {}).get("value")
            elif loinc == "72166-2":
                s.smoking = r.get("valueCodeableConcept", {}).get("text", "")
        elif rt == "Encounter":
            s.setting_label = (r.get("type") or [{}])[0].get("text", "")
            for ext in r.get("extension", []):
                if ext.get("url") == "urn:cds:setting":
                    s.setting = ext.get("valueCode", "")
            s.encounter_note = (r.get("reasonCode") or [{}])[0].get("text", "")
    return s
