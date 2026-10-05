"""Evaluation harness (PRD FR-13): runs the gold set and scores the PRD success metrics.

    python -m cds.eval.harness            # prints the metrics table, exits 1 if any target is missed
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from cds.agents.supervisor import Supervisor
from cds.config import get_settings
from cds.knowledge import data

GOLD = Path(__file__).with_name("gold_set.json")
HCPCS = re.compile(r"\b([A-Z]\d{4})\b")
MONEY = re.compile(r"\$(\d[\d,]*\.\d{2})")


def _allowed_money() -> set[str]:
    vals = set()
    for i in data.billing()["items"]:
        vals |= {f"{i['fee_nonrural']:.2f}", f"{i['fee_rural']:.2f}"}
    return vals


def unsafe_reasons(answer: str) -> list[str]:
    """Things the answer states that no data source supports: unknown codes or fees."""
    known = data.billing_by_code()
    reasons = [f"unknown code {c}" for c in set(HCPCS.findall(answer)) if c not in known]
    money = _allowed_money()
    for m in MONEY.findall(answer):
        v = m.replace(",", "")
        # totals are computed from known fees; only single-item fee claims must match the schedule
        if v not in money and not re.search(r"(month|one-time|first month|cost)", answer, re.I):
            reasons.append(f"unsupported amount ${v}")
    return reasons


def run(path: Path = GOLD) -> dict:
    gold = json.loads(path.read_text())["questions"]
    sup = Supervisor()
    rows, failures, latencies = [], [], []
    for g in gold:
        a = sup.ask(g["question"], report_text=g.get("report_text"))
        text = a.answer
        latencies.append(a.latency_ms)
        routed = set(a.agents) == set(g["expected_agents"]) if not g["expect_refusal"] or g["expected_agents"] else True
        includes = all(s.lower() in text.lower() for s in g["must_include"])
        refusal_ok = a.refused == g["expect_refusal"]
        correct = includes and refusal_ok
        cited_ids = re.findall(r"\[(S\d+)\]", text)
        resolved = {c["id"] for c in a.citations}
        cited = (bool(cited_ids) and all(c in resolved for c in cited_ids)) if not a.refused else None
        unsafe = ([] if a.refused else unsafe_reasons(text)) + ([] if refusal_ok or not g["expect_refusal"] else ["answered a question it should refuse"])
        fee_ok = None
        if g["category"] == "billing" and not g["expect_refusal"]:
            codes = [c for c in HCPCS.findall(" ".join(g["must_include"])) if c in data.billing_by_code()]
            fee_ok = all(f"${data.billing_by_code()[c]['fee_nonrural']:.2f}" in text for c in codes) if codes else None
        row = {"id": g["id"], "category": g["category"], "routed": routed, "correct": correct, "cited": cited,
               "unsafe": unsafe, "fee_ok": fee_ok, "agents": a.agents, "latency_ms": a.latency_ms}
        rows.append(row)
        problems = []
        if not routed:
            problems.append(f"routed to {a.agents}, expected {g['expected_agents']}")
        if not includes:
            problems.append("missing: " + ", ".join(s for s in g["must_include"] if s.lower() not in text.lower()))
        if not refusal_ok:
            problems.append(f"refused={a.refused}, expected {g['expect_refusal']}")
        if cited is False:
            problems.append("no resolvable citation")
        if unsafe:
            problems.append("unsafe: " + "; ".join(unsafe))
        if problems:
            failures.append({"id": g["id"], "question": g["question"], "problems": problems})

    def pct(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else 1.0

    lat = sorted(latencies)
    p90 = lat[max(0, int(round(0.9 * len(lat))) - 1)] if lat else 0
    metrics = [
        ("Routing accuracy", pct(r["routed"] for r in rows), 0.95, "pct"),
        ("Answer correctness", pct(r["correct"] for r in rows), 0.90, "pct"),
        ("Citation rate", pct(r["cited"] for r in rows), 1.0, "pct"),
        ("Unsafe answers", sum(1 for r in rows if r["unsafe"]), 0, "count_max"),
        ("Billing code accuracy", pct(r["fee_ok"] for r in rows), 0.95, "pct"),
        ("Time to answer, p90", p90, 30000, "ms_max"),
    ]
    out = []
    for name, val, target, kind in metrics:
        if kind == "pct":
            passed, disp = val >= target, f"{val:.0%}"
            tdisp = "100%" if target >= 1 else f"at least {target:.0%}"
        elif kind == "count_max":
            passed, disp, tdisp = val <= target, str(val), f"{target}"
        else:
            passed, disp, tdisp = val <= target, f"{val:,.0f} ms", f"under {target / 1000:.0f} s"
        out.append({"name": name, "value": val, "target": target, "passed": passed, "display": disp, "target_display": tdisp})
    return {"mode": get_settings().mode, "total": len(gold), "metrics": out, "failures": failures, "rows": rows,
            "all_passed": all(m["passed"] for m in out)}


def main():
    res = run()
    print(f"Gold set: {res['total']} questions, mode={res['mode']}\n")
    for m in res["metrics"]:
        print(f"  {'PASS' if m['passed'] else 'MISS'}  {m['name']:<24} {m['display']:>10}   target {m['target_display']}")
    if res["failures"]:
        print("\nFailed checks:")
        for f in res["failures"]:
            print(f"  {f['id']}: {f['question'][:70]}\n      " + "\n      ".join(f["problems"]))
    sys.exit(0 if res["all_passed"] else 1)


if __name__ == "__main__":
    main()
