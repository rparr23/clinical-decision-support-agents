"""Load the bundled data sets once and build the local search indexes."""

from __future__ import annotations

import json
from functools import lru_cache

from cds.config import DATA_DIR
from cds.knowledge.fhir import PatientSummary, parse_bundle
from cds.knowledge.textindex import Doc, TfidfIndex


@lru_cache
def guidelines() -> dict:
    return json.loads((DATA_DIR / "acr_routine_chest_imaging.json").read_text())


@lru_cache
def report_checklist() -> dict:
    return json.loads((DATA_DIR / "acr_report_checklist.json").read_text())


@lru_cache
def billing() -> dict:
    return json.loads((DATA_DIR / "billing_respiratory_demo.json").read_text())


@lru_cache
def billing_by_code() -> dict[str, dict]:
    return {i["code"]: i for i in billing()["items"]}


@lru_cache
def patients() -> dict[str, PatientSummary]:
    bundles = json.loads((DATA_DIR / "synthetic_patients.json").read_text())
    out = {}
    for b in bundles:
        p = parse_bundle(b)
        out[p.id] = p
    return out


def guideline_docs() -> list[Doc]:
    g = guidelines()
    src = g["source"]["title"]
    docs = []
    for v in g["variants"]:
        procs = "; ".join(f"{p['procedure']}: {p['category']}" for p in v["procedures"])
        docs.append(Doc(f"variant-{v['variant']}", f"{v['title']} {v['summary']} {procs}",
                        {"source": src, "locator": f"Variant {v['variant']}, p. {v['page']}", "kind": "variant",
                         "variant": v["variant"], "snippet": v["summary"]}))
    for p in g["passages"]:
        docs.append(Doc(p["id"], f"{p['section']}. {p['text']}",
                        {"source": src, "locator": f"{p['section']}, p. {p['page']}", "kind": "passage",
                         "snippet": p["text"]}))
    return docs


def billing_docs() -> list[Doc]:
    return [Doc(i["code"], f"{i['code']} {i['description']} {' '.join(i['keywords'])} {i['category']}", {"item": i})
            for i in billing()["items"]]


@lru_cache
def guideline_index() -> TfidfIndex:
    return TfidfIndex(guideline_docs())


@lru_cache
def billing_index() -> TfidfIndex:
    return TfidfIndex(billing_docs())


@lru_cache
def patient_index() -> TfidfIndex:
    return TfidfIndex([Doc(p.id, p.text(), {"patient": p}) for p in patients().values()])
