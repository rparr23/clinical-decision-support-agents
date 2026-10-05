"""Per-request trace of agent and tool calls, shared by offline and Bedrock modes.

Tools record what they did (and the sources they used) into the active trace, so
citations are collected the same way whichever mode produced the answer.
"""

from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

_current: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("cds_trace", default=None)
# Strands may run tools on worker threads that don't inherit the context; fall back to the request's trace.
_active: "Trace | None" = None


@dataclass
class Citation:
    id: str
    source: str
    locator: str
    snippet: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "locator": self.locator, "snippet": self.snippet, "url": self.url}


@dataclass
class Span:
    kind: str  # "agent" or "tool"
    name: str
    agent: str
    detail: str
    started: float
    ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "agent": self.agent, "detail": self.detail, "ms": round(self.ms, 1)}


@dataclass
class Trace:
    spans: list[Span] = field(default_factory=list)
    citations: dict[str, Citation] = field(default_factory=dict)
    agent_stack: list[str] = field(default_factory=list)

    @property
    def current_agent(self) -> str:
        return self.agent_stack[-1] if self.agent_stack else "supervisor"

    def cite(self, source: str, locator: str, snippet: str = "", url: str = "") -> str:
        key = f"{source}|{locator}"
        for cid, c in self.citations.items():
            if f"{c.source}|{c.locator}" == key:
                return cid
        cid = f"S{len(self.citations) + 1}"
        self.citations[cid] = Citation(cid, source, locator, snippet[:280], url)
        return cid

    def as_list(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self.spans]


def current() -> Trace:
    t = _current.get() or _active
    if t is None:
        t = Trace()
        _current.set(t)
    return t


@contextmanager
def new_trace():
    global _active
    t = Trace()
    token = _current.set(t)
    _active = t
    try:
        yield t
    finally:
        _current.reset(token)
        _active = None


@contextmanager
def span(kind: str, name: str, detail: str = ""):
    t = current()
    s = Span(kind, name, t.current_agent if kind == "tool" else name, detail[:160], time.perf_counter())
    t.spans.append(s)
    if kind == "agent":
        t.agent_stack.append(name)
    try:
        yield s
    finally:
        s.ms = (time.perf_counter() - s.started) * 1000
        if kind == "agent":
            t.agent_stack.pop()
