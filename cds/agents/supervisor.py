"""Medical supervisor: screens the question, routes it to specialist agents and merges a cited answer.

Three modes share this entry point (see cds.config):
- offline   deterministic local agents (default; no AWS needed)
- bedrock   Strands agents calling Claude on Amazon Bedrock
- agentcore forward to a deployed AgentCore Runtime
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from cds import safety, trace
from cds.agents import router
from cds.agents.specialists import AGENT_NAMES, RUNNERS, Section
from cds.config import DISCLAIMER, get_settings


@dataclass
class Answer:
    id: str
    question: str
    answer: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    refusal_reason: str = ""
    mode: str = "offline"
    latency_ms: float = 0.0
    disclaimer: str = DISCLAIMER

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _refuse(question: str, reason: str, message: str, mode: str, t0: float, tr: trace.Trace | None = None,
            agents: list[str] | None = None) -> Answer:
    return Answer(id=uuid.uuid4().hex[:12], question=question, answer=message, refused=True, refusal_reason=reason,
                  agents=agents or [],
                  mode=mode, latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                  trace=tr.as_list() if tr else [])


def _used_citations(text: str, tr: trace.Trace) -> list[dict[str, Any]]:
    used = dict.fromkeys(re.findall(r"\[(S\d+)\]", text))
    return [tr.citations[c].as_dict() for c in used if c in tr.citations]


class Supervisor:
    def __init__(self, mode: str | None = None):
        self.mode = mode or get_settings().mode

    def ask(self, question: str, patient_id: str | None = None, report_text: str | None = None,
            order: str | None = None, setting: str | None = None) -> Answer:
        t0 = time.perf_counter()
        question = (question or "").strip()
        screened = " ".join(x for x in [question, report_text or "", order or ""] if x)
        phi = safety.detect_phi(screened)
        if phi:
            return _refuse(question, "phi", "This looks like it contains real patient identifiers (" + ", ".join(phi)
                           + "). This platform only works with synthetic data. Remove the identifiers and ask again.",
                           self.mode, t0)
        scope = safety.out_of_scope(question)
        if scope:
            return _refuse(question, "out_of_scope", f"I can't help with {scope}. This tool checks imaging guidelines, "
                           "similar synthetic patients and billing rules; a clinician must make treatment decisions.",
                           self.mode, t0)
        if not question and not report_text and not order:
            return _refuse(question, "empty", "Ask a question, pick a patient and order, or paste a report.", self.mode, t0)

        with trace.new_trace() as tr:
            if self.mode == "bedrock":
                from cds.agents import strands_app
                return strands_app.ask(question, patient_id, report_text, order, setting, tr, t0)
            if self.mode == "agentcore":
                from cds.agents import remote
                return remote.ask(question, patient_id, report_text, order, setting, t0)
            return self._offline(question, patient_id, report_text, order, setting, tr, t0)

    def _offline(self, question, patient_id, report_text, order, setting, tr, t0) -> Answer:
        with trace.span("agent", "supervisor", question):
            r = router.route(" ".join(x for x in [question, order or ""] if x), patient_id, report_text)
            ctx = {"patient_id": r.patient_id, "report_text": report_text, "report": r.report,
                   "chart_check": r.chart_check or bool(order), "order": order, "setting": setting or ""}
            agents = list(r.agents)
            if order and "guidelines" not in agents:
                agents.insert(0, "guidelines")
            if not agents:
                # Nothing matched the routing rules: try guidelines search, refuse if it finds nothing (FR-10)
                agents = ["guidelines"]
            sections: list[Section] = [RUNNERS[a](question, ctx) for a in agents]
        confident = [s for s in sections if s.confident]
        if not confident:
            msg = ("I don't have a source that answers this. The loaded knowledge covers ACR routine chest imaging, "
                   "synthetic FHIR patients and a respiratory care fee schedule.\n\n"
                   + "\n\n".join(s.markdown for s in sections))
            return _refuse(question, "no_source", msg, self.mode, t0, tr, agents if r.agents else [])
        if len(sections) == 1:
            body = sections[0].markdown
        else:
            body = "\n\n".join(f"#### {AGENT_NAMES[s.agent]}: {s.title}\n\n{s.markdown}" for s in sections)
        return Answer(id=uuid.uuid4().hex[:12], question=question, answer=body,
                      sections=[s.as_dict() for s in sections], citations=_used_citations(body, tr),
                      agents=agents, trace=tr.as_list(), mode=self.mode,
                      latency_ms=round((time.perf_counter() - t0) * 1000, 1))
