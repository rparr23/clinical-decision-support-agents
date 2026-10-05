"""Input screening: block likely PHI and out-of-scope requests (PRD NFR-1, NFR-3, NFR-4)."""

from __future__ import annotations

import re

PHI_PATTERNS = {
    "Social Security number": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone number": re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"),
    "email address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "medical record number": re.compile(r"\bMRN[:#\s]*\d{5,}\b", re.I),
    "street address": re.compile(r"\b\d{2,5}\s+\w+(\s\w+)?\s(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)\b", re.I),
}

OUT_OF_SCOPE = [
    (re.compile(r"\b(what|which|how much)\b.*\b(dose|dosage|mg)\b|\bhow many (mg|milligrams)\b", re.I),
     "dosing advice"),
    (re.compile(r"\b(do i have|diagnose me|am i dying|should i (stop|start) taking)\b", re.I),
     "personal diagnosis or treatment advice"),
]


def detect_phi(text: str) -> list[str]:
    return [name for name, pat in PHI_PATTERNS.items() if pat.search(text or "")]


def out_of_scope(text: str) -> str | None:
    for pat, label in OUT_OF_SCOPE:
        if pat.search(text or ""):
            return label
    return None


def redact(text: str) -> str:
    """Remove PHI-like strings before anything is logged."""
    for pat in PHI_PATTERNS.values():
        text = pat.sub("[redacted]", text)
    return text
