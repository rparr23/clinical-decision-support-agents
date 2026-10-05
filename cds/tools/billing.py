"""Respiratory billing tools: code lookup, supply cost totals, prior authorization and limit checks."""

from __future__ import annotations

import json
import re
from typing import Any

from cds import trace
from cds.config import get_settings
from cds.knowledge import data, vectors

CODE_RE = re.compile(r"\b([A-Z]\d{4})\b")


def _cite_item(item: dict) -> str:
    src = data.billing()["source"]
    label = "WA HCA fee schedule" if item["source"].startswith("WA HCA") else "Demo respiratory fee schedule (synthetic)"
    return trace.current().cite(label, f"Code {item['code']}", f"{item['code']} {item['description']}: "
                                f"${item['fee_nonrural']:.2f} per {item['unit']}", "")


def _item_from_meta(meta: dict) -> dict | None:
    if "item" in meta:
        return meta["item"]
    if "item_json" in meta:
        return json.loads(meta["item_json"])
    return data.billing_by_code().get(meta.get("id", ""))


def _public(item: dict) -> dict:
    lim = item["limit"]
    return {"code": item["code"], "description": item["description"], "fee_nonrural": item["fee_nonrural"],
            "fee_rural": item["fee_rural"], "unit": item["unit"], "coverage": item["coverage"],
            "limit": f"{lim['quantity']} every {lim['days']} days", "prior_auth_required": item["prior_auth_required"],
            "prior_auth_note": item["prior_auth_note"], "data_source": item["source"]}


def query_billing(query: str, k: int = 4) -> dict[str, Any]:
    """Look up billing codes, fees, coverage limits and prior authorization rules by code or description."""
    with trace.span("tool", "query_billing", query):
        by_code = data.billing_by_code()
        codes = [c for c in CODE_RE.findall(query.upper()) if c in by_code]
        if codes:
            items = [by_code[c] for c in codes]
        else:
            threshold = get_settings().retrieval_threshold
            hits = vectors.search("billing", query, k)
            top = hits[0][2] if hits else 0.0
            # keep hits close to the best one so loosely related items don't pad the answer
            items = [i for _, meta, s in hits if s >= threshold and s >= 0.6 * top
                     for i in [_item_from_meta(meta)] if i]
        unknown = [c for c in CODE_RE.findall(query.upper()) if c not in by_code]
        return {"items": [_public(i) | {"citation": _cite_item(i)} for i in items], "unknown_codes": unknown,
                "below_threshold": not items, "extracted": data.billing()["source"]["extracted"]}


def _resolve(supplies: list[list[Any]] | None, plan: str | None) -> tuple[str, list[tuple[dict, int]]]:
    by_code = data.billing_by_code()
    label = "Custom supply list"
    if plan:
        cp = data.billing()["care_plans"].get(plan)
        if cp:
            label, supplies = cp["label"], cp["supplies"]
    return label, [(by_code[c], int(q)) for c, q in (supplies or []) if c in by_code]


def calculate_supply_costs(plan: str = "", supplies: list[list[Any]] | None = None) -> dict[str, Any]:
    """Total the first-month cost of a care plan (copd, asthma, sleep_apnea, tracheostomy) or a [[code, qty]] list."""
    with trace.span("tool", "calculate_supply_costs", plan or json.dumps(supplies)):
        label, rows = _resolve(supplies, plan)
        lines, monthly, one_time = [], 0.0, 0.0
        for item, qty in rows:
            cost = round(item["fee_nonrural"] * qty, 2)
            recurring = item["unit"] != "purchase"
            if recurring:
                monthly += cost
            else:
                one_time += cost
            lines.append({"code": item["code"], "description": item["description"], "quantity": qty,
                          "unit": item["unit"], "fee": item["fee_nonrural"], "cost": cost,
                          "recurring": recurring, "prior_auth_required": item["prior_auth_required"],
                          "citation": _cite_item(item)})
        return {"plan": label, "lines": lines, "monthly_total": round(monthly, 2), "one_time_total": round(one_time, 2),
                "first_month_total": round(monthly + one_time, 2)}


def check_authorization_and_limits(plan: str = "", supplies: list[list[Any]] | None = None) -> dict[str, Any]:
    """Flag items that need prior authorization or whose 30-day quantity exceeds the coverage limit."""
    with trace.span("tool", "check_authorization_and_limits", plan or json.dumps(supplies)):
        label, rows = _resolve(supplies, plan)
        flags = []
        for item, qty in rows:
            lim = item["limit"]
            allowed_30 = lim["quantity"] * min(30, lim["days"]) / lim["days"] if lim["days"] <= 30 else lim["quantity"]
            over = qty > allowed_30
            if item["prior_auth_required"] or over:
                flags.append({"code": item["code"], "description": item["description"], "requested_30_days": qty,
                              "limit": f"{lim['quantity']} every {lim['days']} days",
                              "prior_auth_required": item["prior_auth_required"], "prior_auth_note": item["prior_auth_note"],
                              "over_limit": over, "citation": _cite_item(item)})
        return {"plan": label, "flags": flags, "checked": len(rows)}
