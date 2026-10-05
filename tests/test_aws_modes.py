"""Bedrock and AgentCore wiring, checked without calling AWS."""

import json

import pytest


def test_strands_supervisor_builds():
    pytest.importorskip("strands")
    from cds.agents import strands_app

    agent = strands_app.build_supervisor()
    assert sorted(agent.tool_names) == ["acr_guidelines_agent", "medical_billing_agent", "patient_similarity_agent"]


def test_agentcore_entrypoint_returns_answer(monkeypatch):
    pytest.importorskip("bedrock_agentcore")
    import agentcore.agentcore_entry as entry
    from cds.agents.supervisor import Supervisor

    monkeypatch.setattr(entry, "Supervisor", lambda mode=None: Supervisor(mode="offline"))
    out = entry.invoke({"prompt": "What is the fee for A4217?"})
    assert "A4217" in out["answer"] and json.dumps(out)


def test_s3vectors_backend_shapes_results(monkeypatch):
    from cds.knowledge import vectors

    class FakeS3V:
        def query_vectors(self, **kw):
            assert kw["indexName"] == "respiratory-billing-index" and kw["topK"] == 4
            item = {"code": "A4216"}
            return {"vectors": [{"key": "A4216", "distance": 0.1, "metadata": {"text": "sterile water", "item_json": json.dumps(item)}}]}

    monkeypatch.setenv("CDS_VECTOR_BACKEND", "s3vectors")
    monkeypatch.setattr(vectors, "_clients", lambda: (None, FakeS3V()))
    monkeypatch.setattr(vectors, "embed", lambda text: [0.0] * 1024)
    hits = vectors.search("billing", "sterile water", 4)
    assert hits[0][1]["id"] == "A4216" and abs(hits[0][2] - 0.9) < 1e-9
