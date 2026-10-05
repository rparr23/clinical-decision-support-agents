"""FastAPI web app: branded chat UI plus JSON API over the supervisor and tools.

Run:  uvicorn app.server:app --reload   then open http://localhost:8000
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cds import __version__, safety
from cds.agents.supervisor import Supervisor
from cds.config import DISCLAIMER, get_settings
from cds.knowledge import data
from cds.tools import guidelines

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="ClearPath CDS", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskRequest(BaseModel):
    question: str = Field("", max_length=4000)
    patient_id: str | None = None
    report_text: str | None = Field(None, max_length=20000)
    order: str | None = Field(None, max_length=500)
    setting: str | None = None


class ReportRequest(BaseModel):
    text: str = Field(..., max_length=20000)


class FeedbackRequest(BaseModel):
    answer_id: str
    rating: int = Field(..., ge=-1, le=1)
    reason: str = Field("", max_length=1000)
    question: str = Field("", max_length=4000)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/config")
def config():
    s = get_settings()
    return {"brand": s.brand_name, "mode": s.mode, "model_id": s.model_id, "vector_backend": s.vector_backend,
            "disclaimer": DISCLAIMER, "billing_extracted": data.billing()["source"]["extracted"],
            "guideline": data.guidelines()["source"]["title"] + " (revised " + data.guidelines()["source"]["revised"] + ")",
            "patients": len(data.patients()), "billing_items": len(data.billing()["items"])}


@app.get("/api/patients")
def list_patients():
    return [{"id": p.id, "label": f"{p.id} · {p.age}{p.sex[0].upper()} · "
             + (", ".join(c.display for c in p.conditions[:2]) or "no chronic conditions"),
             "setting": p.setting} for p in data.patients().values()]


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str):
    p = data.patients().get(patient_id.upper())
    if not p:
        raise HTTPException(404, "No synthetic patient with that id")
    return p.as_dict()


@app.post("/api/ask")
def ask(req: AskRequest):
    return Supervisor().ask(req.question, req.patient_id or None, req.report_text or None, req.order or None,
                            req.setting or None).as_dict()


@app.post("/api/validate-report")
def validate_report(req: ReportRequest):
    if safety.detect_phi(req.text):
        raise HTTPException(422, "The report looks like it contains real identifiers. Use synthetic text only.")
    return guidelines.validate_radiology_report(req.text)


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    path = get_settings().feedback_path
    path.parent.mkdir(parents=True, exist_ok=True)
    row = req.model_dump() | {"question": safety.redact(req.question), "reason": safety.redact(req.reason),
                              "ts": time.time()}
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return {"saved": True}


@app.post("/api/eval")
def run_eval():
    from cds.eval.harness import run

    return run()
