from fastapi.testclient import TestClient

from app.server import app

client = TestClient(app)


def test_health_and_config():
    assert client.get("/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["brand"] == "ClearPath CDS" and cfg["mode"] == "offline" and cfg["patients"] == 120


def test_index_is_branded():
    html = client.get("/").text
    assert "ClearPath CDS" in html and "/static/app.js" in html
    css = client.get("/static/styles.css").text
    assert "skyline.jpg" in css
    assert client.get("/static/brand/skyline.jpg").status_code == 200


def test_patients():
    pts = client.get("/api/patients").json()
    assert len(pts) == 120 and pts[0]["id"] == "P-0001"
    assert client.get("/api/patients/P-0002").json()["age"] > 0
    assert client.get("/api/patients/P-9999").status_code == 404


def test_ask():
    r = client.post("/api/ask", json={"question": "What is the billing code and fee for sterile water used in nebulizer treatments?"}).json()
    assert "A4216" in r["answer"] and r["agents"] == ["billing"] and r["citations"]


def test_validate_report_blocks_phi():
    assert client.post("/api/validate-report", json={"text": "MRN 1234567 FINDINGS: clear"}).status_code == 422
    ok = client.post("/api/validate-report", json={"text": "FINDINGS: clear. IMPRESSION: normal."}).json()
    assert ok["verdict"] == "incomplete"


def test_feedback(tmp_path, monkeypatch):
    path = tmp_path / "fb.jsonl"
    monkeypatch.setenv("CDS_FEEDBACK_PATH", str(path))
    r = client.post("/api/feedback", json={"answer_id": "abc", "rating": 1, "question": "call 206-555-0123"})
    assert r.json()["saved"] and "[redacted]" in path.read_text()


def test_eval_endpoint():
    r = client.post("/api/eval").json()
    assert r["total"] == 50 and r["all_passed"], r["failures"]
