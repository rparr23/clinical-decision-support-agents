"""ACR guideline tools: search, imaging appropriateness lookup and report validation."""

from __future__ import annotations

import re
from typing import Any

from cds import trace
from cds.config import get_settings
from cds.knowledge import data, vectors

SCENARIOS = {
    "admission": 1,
    "preop": 2,
    "preop_chronic": 3,
    "surveillance": 4,
}


def _cite_variant(v: dict) -> str:
    g = data.guidelines()
    return trace.current().cite(g["source"]["title"], f"Variant {v['variant']}, p. {v['page']}", v["summary"],
                                g["source"]["url"])


def search_guidelines(query: str, k: int = 3) -> dict[str, Any]:
    """Search ACR guideline passages and variant tables. Returns passages with citations and scores."""
    with trace.span("tool", "search_guidelines", query):
        hits = vectors.search("guidelines", query, k)
        threshold = get_settings().retrieval_threshold
        results = []
        for text, meta, score in hits:
            if score < threshold:
                continue
            cid = trace.current().cite(meta.get("source", "ACR guideline"), meta.get("locator", meta["id"]),
                                       meta.get("snippet", text), data.guidelines()["source"]["url"])
            results.append({"citation": cid, "text": meta.get("snippet", text), "locator": meta.get("locator"),
                            "kind": meta.get("kind"), "variant": meta.get("variant"), "score": round(score, 3)})
        return {"results": results, "below_threshold": not results}


def normalize_procedure(text: str) -> str | None:
    """Map free-text order wording to a procedure name in the ACR variant tables."""
    t = (text or "").lower()
    with_and_without = bool(re.search(r"with(out)? and with(out)?|w/?o? and w/?|w and w/?o", t))
    without = bool(re.search(r"without|non-?contrast|no contrast|w/o|noncon", t))
    with_c = bool(re.search(r"with (iv )?contrast|contrast[- ]enhanced|w/ ?contrast|with iv", t))
    if re.search(r"\bpet\b|fdg", t):
        return "FDG-PET/CT skull base to mid-thigh"
    if re.search(r"\bcta\b|ct angio|angiogra", t):
        return "CTA chest without and with IV contrast" if with_and_without else "CTA chest with IV contrast"
    if re.search(r"\bmri\b|\bmr\b|magnetic", t):
        return "MRI chest without and with IV contrast" if (with_and_without or with_c) else "MRI chest without IV contrast"
    if re.search(r"\bct\b|computed tomograph|cat scan", t):
        if with_and_without:
            return "CT chest without and with IV contrast"
        if with_c and not without:
            return "CT chest with IV contrast"
        return "CT chest without IV contrast"
    if re.search(r"x-?ray|radiograph|\bcxr\b|chest film|pa and lateral|portable chest", t):
        return "Radiography chest"
    return None


def check_imaging_appropriateness(procedure: str, scenario: str) -> dict[str, Any]:
    """Look up the ACR appropriateness category for a chest imaging procedure in a routine-imaging scenario.

    scenario is one of: admission, preop, preop_chronic, surveillance.
    """
    with trace.span("tool", "check_imaging_appropriateness", f"{procedure} / {scenario}"):
        proc = normalize_procedure(procedure) or procedure
        vnum = SCENARIOS.get(scenario)
        variant = next((v for v in data.guidelines()["variants"] if v["variant"] == vnum), None)
        if variant is None:
            return {"found": False, "reason": f"Unknown scenario '{scenario}'"}
        row = next((p for p in variant["procedures"] if p["procedure"].lower() == proc.lower()), None)
        cid = _cite_variant(variant)
        better = [p["procedure"] for p in variant["procedures"]
                  if p["category"] != "Usually Not Appropriate" and p["procedure"] != (row or {}).get("procedure")]
        if row is None:
            return {"found": False, "variant": vnum, "variant_title": variant["title"], "citation": cid,
                    "reason": f"'{procedure}' is not rated in this ACR topic"}
        return {"found": True, "variant": vnum, "variant_title": variant["title"], "procedure": row["procedure"],
                "category": row["category"], "relative_radiation_level": row["relative_radiation_level"],
                "summary": variant["summary"], "alternatives_rated_higher": better, "citation": cid}


def validate_radiology_report(report_text: str) -> dict[str, Any]:
    """Check a radiology report against the ACR communication checklist. Returns pass/gap per item."""
    with trace.span("tool", "validate_radiology_report", report_text[:80]):
        cl = data.report_checklist()
        text = (report_text or "").lower()
        cid = trace.current().cite(cl["source"]["title"], "Report components", "", cl["source"]["url"])
        items, gaps = [], []
        for it in cl["items"]:
            present = any(re.search(p, text) for p in it["patterns"])
            if it["required"] == "conditional":
                triggered = [p for p in it["trigger_patterns"] if re.search(p, text)]
                applies = bool(triggered) and not re.search(r"\bno (evidence of )?(" + "|".join(triggered) + r")", text)
                status = "na" if not applies else ("pass" if present else "gap")
                severity = "critical" if status == "gap" else "info"
                note = it["guidance"] if applies else "No urgent finding detected; not required."
            else:
                status = "pass" if present else ("gap" if it["required"] else "suggestion")
                severity = "major" if status == "gap" else ("minor" if status == "suggestion" else "info")
                note = "" if present else it["guidance"]
            row = {"id": it["id"], "label": it["label"], "status": status, "severity": severity, "note": note,
                   "citation": cid}
            items.append(row)
            if status in ("gap", "suggestion"):
                gaps.append(row)
        required_gaps = [g for g in gaps if g["severity"] in ("major", "critical")]
        verdict = "complete" if not required_gaps else ("critical gap" if any(
            g["severity"] == "critical" for g in gaps) else "incomplete")
        return {"verdict": verdict, "items": items, "gaps": gaps,
                "passed": sum(1 for i in items if i["status"] == "pass"),
                "total": sum(1 for i in items if i["status"] != "na"), "citation": cid}
