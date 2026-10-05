"""Offline specialist agents. Each calls its tools and writes a short cited answer section."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cds import trace
from cds.tools import billing as billing_tools
from cds.tools import chart_check, guidelines, patients
from cds.agents.router import CARE_PLAN_WORDS

AGENT_NAMES = {
    "guidelines": "ACR Guidelines Agent",
    "patients": "Patient Similarity Agent",
    "billing": "Medical Billing Agent",
}


@dataclass
class Section:
    agent: str
    title: str
    markdown: str
    confident: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "agent_name": AGENT_NAMES[self.agent], "title": self.title,
                "markdown": self.markdown, "confident": self.confident, "data": self.data}


def _cite(*ids: str | None) -> str:
    ids = [i for i in ids if i]
    return " " + "".join(f"[{i}]" for i in dict.fromkeys(ids)) if ids else ""


# --------------------------------------------------------------------------- guidelines

def _scenario_from_text(q: str) -> str | None:
    t = q.lower()
    no_chronic = re.search(r"\b(no|without|absence of)\b[\w ,]{0,40}\b(history|chronic|cardiopulmonary|lung|heart)", t)
    chronic = re.search(r"\b(copd|emphysema|asthma|heart failure|chf|coronary|interstitial|ild|chronic "
                        r"cardiopulmonary|cardiothoracic surgery|chronic (lung|heart))", t) and not no_chronic
    if re.search(r"surveillance|follow-?up|stable|monitor", t) and (chronic or "chronic" in t):
        return "surveillance"
    if re.search(r"pre-?op|preoperative|before [\w -]{0,30}(surgery|operation|replacement|repair)|surgical clearance|prior to [\w -]{0,30}surgery", t):
        return "preop_chronic" if chronic else "preop"
    if re.search(r"\badmi(t|ssion|tted)|hospitali[sz]", t):
        return "surveillance" if chronic else "admission"
    return None


def _md_report(res: dict) -> str:
    lines = [f"**Report check: {res['verdict']}** ({res['passed']} of {res['total']} items present){_cite(res['citation'])}",
             ""]
    for it in res["items"]:
        if it["status"] == "na":
            continue
        mark = {"pass": "Present", "gap": "Missing", "suggestion": "Consider adding"}[it["status"]]
        extra = f": {it['note']}" if it["status"] in ("gap", "suggestion") and it["note"] else ""
        lines.append(f"- {mark}: {it['label']}{extra}")
    return "\n".join(lines)


def run_guidelines(question: str, ctx: dict) -> Section:
    with trace.span("agent", "guidelines", question):
        if ctx.get("report_text") or ctx.get("report"):
            text = ctx.get("report_text") or question
            res = guidelines.validate_radiology_report(text)
            return Section("guidelines", "Radiology report validation", _md_report(res), True, res)

        order = ctx.get("order") or question
        if ctx.get("patient_id") and (ctx.get("chart_check") or ctx.get("order")):
            res = chart_check.check_order_against_chart(ctx["patient_id"], order, ctx.get("setting", ""))
            if not res.get("found"):
                return Section("guidelines", "Order check", res["reason"], False, res)
            head = {"consistent": "Consistent with ACR criteria", "review": "Review needed",
                    "not supported": "Not supported by ACR criteria",
                    "outside routine imaging": "Outside the routine imaging criteria",
                    "not assessable": "Not assessable"}[res["verdict"]]
            md = [f"**{head}.** Order: {res['procedure'] or res['order']} for patient {res['patient_id']}"
                  f"{_cite(res['chart_citation'])}"]
            if res.get("category"):
                md.append(f"ACR rates this procedure **{res['category']}** for Variant {res['variant']} "
                          f"(relative radiation: {res['relative_radiation_level']}). {res['explanation']}"
                          f"{_cite(res['guideline_citation'])}")
            else:
                md.append(res["explanation"] + _cite(res.get("guideline_citation")))
            md.append("Chart facts used: " + " ".join(res["reasons"]))
            for n in res["notes"]:
                md.append(f"Note: {n}")
            if res.get("alternatives_rated_higher"):
                md.append("Rated higher in this variant: " + ", ".join(res["alternatives_rated_higher"]) + ".")
            return Section("guidelines", "Chart-to-guideline order check", "\n\n".join(md), True, res)

        proc = guidelines.normalize_procedure(question)
        scenario = _scenario_from_text(question)
        if scenario:
            if proc:
                res = guidelines.check_imaging_appropriateness(proc, scenario)
                md = (f"**{res['procedure']}: {res['category']}** for ACR Variant {res['variant']} "
                      f"({res['variant_title']}){_cite(res['citation'])}\n\n{res['summary']}"
                      f" Relative radiation level: {res['relative_radiation_level']}.")
                if res["alternatives_rated_higher"]:
                    md += "\n\nRated higher in this variant: " + ", ".join(res["alternatives_rated_higher"]) + "."
                return Section("guidelines", "Imaging appropriateness", md, True, res)
            res = guidelines.check_imaging_appropriateness("Radiography chest", scenario)
            from cds.knowledge import data
            v = next(x for x in data.guidelines()["variants"] if x["variant"] == res["variant"])
            rows = "\n".join(f"| {p['procedure']} | {p['category']} | {p['relative_radiation_level']} |"
                             for p in v["procedures"])
            md = (f"**ACR Variant {v['variant']}:** {v['summary']}{_cite(res['citation'])}\n\n"
                  f"| Procedure | ACR category | Radiation |\n| --- | --- | --- |\n{rows}")
            return Section("guidelines", "Imaging appropriateness", md, True, res)

        query = question
        if CARE_PLAN_WORDS.search(question) and not proc:
            query = question + " chronic stable cardiopulmonary disease surveillance chest imaging"
        res = guidelines.search_guidelines(query, k=3)
        if res["below_threshold"]:
            return Section("guidelines", "Guideline search", "No ACR passage in the loaded guidelines matches this "
                           "question closely enough to answer.", False, res)
        top = res["results"]
        md = [f"- {r['text']}{_cite(r['citation'])}" for r in top]
        return Section("guidelines", "Relevant ACR guidance", "\n".join(md), True, res)


# --------------------------------------------------------------------------- patients

def run_patients(question: str, ctx: dict) -> Section:
    with trace.span("agent", "patients", question):
        res = patients.find_similar_patients(question, ctx.get("patient_id") or "", k=5)
        if not res["matches"]:
            return Section("patients", "Similar patients", "No similar synthetic patients found.", False, res)
        prof = res["profile"]
        desc = ", ".join(x for x in [f"{prof['age']} years" if prof["age"] else "", prof["sex"] or "",
                                     ", ".join(prof["conditions"])] if x)
        rows = "\n".join(
            f"| {m['id']} | {m['age']} | {m['sex']} | {', '.join(m['conditions']) or 'none'} | {m['similarity']:.2f} |"
            for m in res["matches"])
        cites = _cite(*[m["citation"] for m in res["matches"]])
        md = (f"**{len(res['matches'])} similar synthetic patients** for: {desc or 'the description given'}{cites}\n\n"
              f"| Patient | Age | Sex | Conditions | Similarity |\n| --- | --- | --- | --- | --- |\n{rows}")
        return Section("patients", "Similar patients", md, True, res)


# --------------------------------------------------------------------------- billing

PLAN_MAP = [(r"copd|emphysema", "copd"), (r"asthma", "asthma"), (r"sleep apnea|cpap|\bosa\b", "sleep_apnea"),
            (r"tracheostomy|\btrach\b", "tracheostomy")]


def _plan(question: str) -> str | None:
    t = question.lower()
    if not re.search(r"suppl|need|plan|cost|total|how much|diagnos|start|set up|setup", t):
        return None
    if billing_tools.CODE_RE.search(question.upper()):
        return None
    for pat, plan in PLAN_MAP:
        if re.search(pat, t):
            return plan
    return None


def _quantities(question: str) -> list[list]:
    out = []
    for m in re.finditer(r"(\d+)\s*(?:units?|x|of)?\s*(?:of\s+)?([A-Z]\d{4})\b|([A-Z]\d{4})\s*(?:x|qty|quantity)?\s*(\d+)",
                         question.upper(), re.I):
        code, qty = (m.group(2), m.group(1)) if m.group(2) else (m.group(3), m.group(4))
        out.append([code, int(qty)])
    return out


def run_billing(question: str, ctx: dict) -> Section:
    with trace.span("agent", "billing", question):
        plan = _plan(question)
        qty = _quantities(question)
        if plan:
            cost = billing_tools.calculate_supply_costs(plan=plan)
            auth = billing_tools.check_authorization_and_limits(plan=plan)
            rows = "\n".join(
                f"| {l['code']} | {l['description']} | {l['quantity']} | ${l['fee']:.2f} / {l['unit']} | "
                f"${l['cost']:.2f} | {'Yes' if l['prior_auth_required'] else 'No'} |" for l in cost["lines"])
            cites = _cite(*[l["citation"] for l in cost["lines"]])
            md = [f"**{cost['plan']}: about ${cost['monthly_total']:.2f} a month** in recurring supplies, plus "
                  f"${cost['one_time_total']:.2f} one-time equipment (first month ${cost['first_month_total']:.2f}){cites}",
                  "", "| Code | Item | Qty | Fee | Cost | Prior auth |", "| --- | --- | --- | --- | --- | --- |", rows]
            pa = [f for f in auth["flags"] if f["prior_auth_required"]]
            if pa:
                md += ["", "**Prior authorization needed:** " + "; ".join(
                    f"{f['code']} ({f['prior_auth_note']})" for f in pa) + "."]
            return Section("billing", "Supply plan and costs", "\n".join(md), True, {"cost": cost, "auth": auth})
        if qty:
            auth = billing_tools.check_authorization_and_limits(supplies=qty)
            looked = billing_tools.query_billing(" ".join(c for c, _ in qty))
            if not looked["items"]:
                return Section("billing", "Limit check", "None of those codes are in the loaded fee schedule.", False,
                               {"auth": auth})
            md = []
            flagged = {f["code"]: f for f in auth["flags"]}
            for it in looked["items"]:
                f = flagged.get(it["code"])
                req = dict(qty).get(it["code"])
                status = []
                if f and f["over_limit"]:
                    status.append(f"**over the limit** ({req} requested, limit {it['limit']})")
                else:
                    status.append(f"within the limit ({req} requested, limit {it['limit']})")
                if it["prior_auth_required"]:
                    status.append(f"prior authorization required: {it['prior_auth_note']}")
                md.append(f"- {it['code']} {it['description']} (${it['fee_nonrural']:.2f} per {it['unit']}): "
                          + "; ".join(status) + _cite(it["citation"]))
            return Section("billing", "Coverage limit and prior authorization check", "\n".join(md), True,
                           {"auth": auth})
        res = billing_tools.query_billing(question)
        if res["below_threshold"]:
            msg = "No matching code in the loaded fee schedule."
            if res["unknown_codes"]:
                msg = f"{', '.join(res['unknown_codes'])} is not in the loaded fee schedule, so I can't give a fee or limit."
            return Section("billing", "Billing lookup", msg, False, res)
        lines = []
        for it in res["items"]:
            pa = f" Prior authorization required: {it['prior_auth_note']}." if it["prior_auth_required"] else \
                " No prior authorization required."
            lines.append(f"- **{it['code']}** {it['description']}: ${it['fee_nonrural']:.2f} per {it['unit']} "
                         f"(rural ${it['fee_rural']:.2f}), coverage {it['coverage'].lower()}, limit {it['limit']}."
                         f"{pa}{_cite(it['citation'])}")
        note = f"\n\nFee data extracted {res['extracted']}."
        return Section("billing", "Billing lookup", "\n".join(lines) + note, True, res)


RUNNERS = {"guidelines": run_guidelines, "patients": run_patients, "billing": run_billing}
