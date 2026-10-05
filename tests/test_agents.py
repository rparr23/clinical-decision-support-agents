from cds.agents.router import route
from cds.agents.supervisor import Supervisor


def test_routing():
    assert route("Is a chest x-ray appropriate on admission?").agents == ["guidelines"]
    assert route("What is the fee for A4216?").agents == ["billing"]
    assert route("Find patients similar to a 50 year old with asthma").agents == ["patients"]
    assert route("I was diagnosed with COPD, what supplies will I need and what do they cost?").agents == ["guidelines", "billing"]
    r = route("Check a chest x-ray for P-0002")
    assert r.chart_check and r.patient_id == "P-0002"
    assert route("x", report_text="FINDINGS: clear").report


def test_answers_are_cited():
    a = Supervisor().ask("Is a chest x-ray appropriate on hospital admission with no cardiopulmonary symptoms?")
    assert not a.refused and "Usually Not Appropriate" in a.answer
    assert a.citations and all(f"[{c['id']}]" in a.answer for c in a.citations)
    assert [s["name"] for s in a.trace if s["kind"] == "agent"] == ["supervisor", "guidelines"]


def test_multi_agent_answer_has_sections():
    a = Supervisor().ask("I was diagnosed with COPD. What supplies will I need and what will they cost?")
    assert a.agents == ["guidelines", "billing"] and len(a.sections) == 2
    assert "ACR Guidelines Agent" in a.answer and "Medical Billing Agent" in a.answer


def test_phi_is_blocked():
    a = Supervisor().ask("Check imaging for patient SSN 123-45-6789")
    assert a.refused and a.refusal_reason == "phi"


def test_dosing_is_refused():
    a = Supervisor().ask("What dose of prednisone should I give?")
    assert a.refused and a.refusal_reason == "out_of_scope"


def test_unanswerable_is_refused():
    a = Supervisor().ask("Who won the World Cup in 2010?")
    assert a.refused and a.refusal_reason == "no_source"


def test_order_and_setting_parameters():
    a = Supervisor().ask("", patient_id="P-0001", order="chest x-ray", setting="preop")
    assert a.sections[0]["data"]["variant"] == 2
