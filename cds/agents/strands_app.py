"""Bedrock mode: the same tools, driven by Claude through Strands Agents ("agents as tools").

The supervisor agent delegates to three specialist agents, each with its own tools. Tools
record sources on the shared trace, so citations and the trace view work as in offline mode.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from functools import lru_cache

from cds import trace
from cds.config import get_settings
from cds.tools import billing as billing_tools
from cds.tools import chart_check, guidelines, patients

CITE_RULE = ("Tool results contain citation ids such as S1. After every factual statement, put the id(s) it came "
             "from in square brackets, for example [S1]. Never state a guideline rating, code, fee or limit that no "
             "tool returned. If the tools return nothing relevant, say you have no source.")

GUIDELINES_PROMPT = f"""You are the ACR Guidelines Agent. You answer chest imaging appropriateness questions from the
ACR Routine Chest Imaging criteria, check planned orders against a synthetic patient's chart, and validate radiology
reports against the ACR communication checklist. Prefer check_order_against_chart when a patient id and an order are
given; check_imaging_appropriateness when a scenario is described; validate_radiology_report for pasted reports.
{CITE_RULE}"""
PATIENTS_PROMPT = f"""You are the Patient Similarity Agent. You find similar synthetic FHIR patients and summarize
charts. All records are synthetic. {CITE_RULE}"""
BILLING_PROMPT = f"""You are the Medical Billing Agent. You look up respiratory care codes, fees, coverage limits and
prior authorization rules, total care-plan costs and flag limit or authorization problems. Say when a fee comes from
the synthetic demo schedule. {CITE_RULE}"""
SUPERVISOR_PROMPT = f"""You are the medical supervisor for a clinical decision support platform used with synthetic
data. Delegate to: acr_guidelines_agent (imaging appropriateness, order checks, report validation),
patient_similarity_agent (similar patients, chart summaries), medical_billing_agent (codes, fees, limits, prior
authorization, supply costs). Use several agents when a question spans areas. Merge their answers into one concise
reply, keep every [S#] citation exactly as the agents gave it, and label which agent supplied each part. Never give
dosing or personal treatment advice. Results require professional medical judgment. {CITE_RULE}"""


def _strands():
    from strands import Agent, tool
    from strands.models import BedrockModel

    return Agent, tool, BedrockModel


@lru_cache
def _model():
    _, _, BedrockModel = _strands()
    s = get_settings()
    return BedrockModel(model_id=s.model_id, region_name=s.region, temperature=0.1, streaming=False)


def _j(x) -> str:
    return json.dumps(x, default=str)


@lru_cache
def build_supervisor():
    Agent, tool, _ = _strands()

    @tool
    def search_guidelines(query: str) -> str:
        """Search ACR Routine Chest Imaging passages and variant tables. Returns passages with citation ids."""
        return _j(guidelines.search_guidelines(query))

    @tool
    def check_imaging_appropriateness(procedure: str, scenario: str) -> str:
        """ACR category for a chest imaging procedure. scenario: admission, preop, preop_chronic or surveillance."""
        return _j(guidelines.check_imaging_appropriateness(procedure, scenario))

    @tool
    def check_order_against_chart(patient_id: str, order: str, setting: str = "") -> str:
        """Check a planned chest imaging order for a synthetic patient (id like P-0002) against ACR criteria."""
        return _j(chart_check.check_order_against_chart(patient_id, order, setting))

    @tool
    def validate_radiology_report(report_text: str) -> str:
        """Check a radiology report against the ACR communication checklist; returns pass or gap per item."""
        return _j(guidelines.validate_radiology_report(report_text))

    @tool
    def find_similar_patients(query: str = "", patient_id: str = "") -> str:
        """Find similar synthetic patients from a described profile or an existing patient id."""
        return _j(patients.find_similar_patients(query, patient_id))

    @tool
    def get_patient_chart(patient_id: str) -> str:
        """Summarized synthetic chart for one patient id."""
        return _j(patients.get_patient_chart(patient_id))

    @tool
    def query_billing(query: str) -> str:
        """Look up respiratory care codes, fees, coverage limits and prior authorization rules."""
        return _j(billing_tools.query_billing(query))

    @tool
    def calculate_supply_costs(plan: str = "", supplies_json: str = "") -> str:
        """Cost a care plan (copd, asthma, sleep_apnea, tracheostomy) or a JSON list of [code, qty] pairs."""
        return _j(billing_tools.calculate_supply_costs(plan, json.loads(supplies_json) if supplies_json else None))

    @tool
    def check_authorization_and_limits(plan: str = "", supplies_json: str = "") -> str:
        """Flag prior authorization needs and 30-day limit overruns for a care plan or JSON [code, qty] list."""
        return _j(billing_tools.check_authorization_and_limits(
            plan, json.loads(supplies_json) if supplies_json else None))

    def specialist(name, prompt, tools):
        def run(query: str) -> str:
            with trace.span("agent", name, query):
                return str(Agent(model=_model(), system_prompt=prompt, tools=tools, callback_handler=None)(query))
        return run

    g = specialist("guidelines", GUIDELINES_PROMPT, [search_guidelines, check_imaging_appropriateness,
                                                     check_order_against_chart, validate_radiology_report])
    p = specialist("patients", PATIENTS_PROMPT, [find_similar_patients, get_patient_chart])
    b = specialist("billing", BILLING_PROMPT, [query_billing, calculate_supply_costs, check_authorization_and_limits])

    @tool
    def acr_guidelines_agent(query: str) -> str:
        """ACR imaging appropriateness, chart-to-guideline order checks and radiology report validation."""
        return g(query)

    @tool
    def patient_similarity_agent(query: str) -> str:
        """Similar synthetic patients and chart summaries."""
        return p(query)

    @tool
    def medical_billing_agent(query: str) -> str:
        """Respiratory codes, fees, coverage limits, prior authorization and supply cost totals."""
        return b(query)

    return Agent(model=_model(), system_prompt=SUPERVISOR_PROMPT, callback_handler=None,
                 tools=[acr_guidelines_agent, patient_similarity_agent, medical_billing_agent])


def ask(question, patient_id, report_text, order, setting, tr: trace.Trace, t0: float):
    from cds.agents.supervisor import Answer, _used_citations

    parts = [question]
    if patient_id:
        parts.append(f"Patient id: {patient_id}.")
    if order:
        parts.append(f"Planned order: {order}." + (f" Setting: {setting}." if setting else ""))
    if report_text:
        parts.append(f"Radiology report to validate:\n{report_text}")
    with trace.span("agent", "supervisor", question):
        text = str(build_supervisor()("\n".join(parts)))
    agents = [s["name"] for s in tr.as_list() if s["kind"] == "agent" and s["name"] != "supervisor"]
    cites = _used_citations(text, tr)
    refused = not cites and bool(re.search(r"no source|don't have|do not have", text, re.I))
    return Answer(id=uuid.uuid4().hex[:12], question=question, answer=text, citations=cites,
                  agents=list(dict.fromkeys(agents)), trace=tr.as_list(), mode="bedrock", refused=refused,
                  refusal_reason="no_source" if refused else "",
                  latency_ms=round((time.perf_counter() - t0) * 1000, 1))
