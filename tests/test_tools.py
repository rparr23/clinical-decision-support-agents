from cds import trace
from cds.knowledge import data
from cds.tools import billing, chart_check, guidelines, patients


def test_data_loads():
    assert len(data.patients()) == 120
    assert len(data.guidelines()["variants"]) == 4
    assert all(len(v["procedures"]) == 9 for v in data.guidelines()["variants"])
    assert data.billing_by_code()["A4216"]["fee_nonrural"] == 0.41


def test_patients_are_synthetic():
    for p in data.patients().values():
        assert p.as_dict()["synthetic"] is True


def test_normalize_procedure():
    cases = {
        "chest x-ray PA and lateral": "Radiography chest",
        "CXR": "Radiography chest",
        "CT chest without contrast": "CT chest without IV contrast",
        "CT chest with IV contrast": "CT chest with IV contrast",
        "CT chest with and without contrast": "CT chest without and with IV contrast",
        "CTA chest": "CTA chest with IV contrast",
        "MRI chest": "MRI chest without IV contrast",
        "PET/CT": "FDG-PET/CT skull base to mid-thigh",
        "knee MRI arthrogram": "MRI chest without IV contrast",
        "echocardiogram": None,
    }
    for text, expected in cases.items():
        assert guidelines.normalize_procedure(text) == expected, text


def test_imaging_appropriateness_matches_acr_tables():
    with trace.new_trace():
        assert guidelines.check_imaging_appropriateness("chest x-ray", "admission")["category"] == "Usually Not Appropriate"
        assert guidelines.check_imaging_appropriateness("chest x-ray", "preop")["category"] == "Usually Not Appropriate"
        assert guidelines.check_imaging_appropriateness("chest x-ray", "preop_chronic")["category"] == "May Be Appropriate"
        r = guidelines.check_imaging_appropriateness("CT chest without contrast", "surveillance")
        assert r["category"] == "May Be Appropriate" and r["variant"] == 4
        assert guidelines.check_imaging_appropriateness("x", "nonsense")["found"] is False


def test_search_records_citations():
    with trace.new_trace() as t:
        r = guidelines.search_guidelines("routine chest radiography on hospital admission")
        assert r["results"] and not r["below_threshold"]
        assert r["results"][0]["citation"] in t.citations


def test_search_refuses_unrelated_query():
    with trace.new_trace():
        assert guidelines.search_guidelines("capital of France")["below_threshold"]


def test_report_validation():
    with trace.new_trace():
        full = guidelines.validate_radiology_report(
            "EXAM: chest PA and lateral. INDICATION: cough. COMPARISON: none available. FINDINGS: clear. "
            "IMPRESSION: normal. Recommend no follow-up.")
        assert full["verdict"] == "complete"
        crit = guidelines.validate_radiology_report(
            "INDICATION: dyspnea. TECHNIQUE: AP portable. COMPARISON: none. FINDINGS: large pneumothorax. IMPRESSION: pneumothorax.")
        assert crit["verdict"] == "critical gap"
        negated = guidelines.validate_radiology_report(
            "INDICATION: cough. TECHNIQUE: PA view. COMPARISON: none. FINDINGS: no pneumothorax. IMPRESSION: normal.")
        assert negated["verdict"] == "complete"


def test_chart_checks():
    with trace.new_trace():
        assert chart_check.check_order_against_chart("P-0001", "chest x-ray")["verdict"] == "not supported"
        r = chart_check.check_order_against_chart("P-0002", "chest x-ray")
        assert r["verdict"] == "review" and r["variant"] == 3
        r3 = chart_check.check_order_against_chart("P-0003", "chest x-ray")
        assert any("pacemaker" in n for n in r3["notes"])
        assert chart_check.check_order_against_chart("P-0005", "chest x-ray")["verdict"] == "outside routine imaging"
        assert chart_check.check_order_against_chart("P-0004", "CT chest with contrast")["verdict"] == "not supported"
        assert chart_check.check_order_against_chart("P-9999", "chest x-ray")["found"] is False
        assert chart_check.check_order_against_chart("P-0001", "echocardiogram")["verdict"] == "not assessable"
        assert chart_check.check_order_against_chart("P-0001", "chest x-ray", "preop")["variant"] == 2


def test_billing_lookup_and_limits():
    with trace.new_trace():
        r = billing.query_billing("sterile water for nebulizer")
        assert [i["code"] for i in r["items"]][:2] == ["A4216", "A4217"]
        assert billing.query_billing("Z9999")["unknown_codes"] == ["Z9999"]
        flags = billing.check_authorization_and_limits(supplies=[["A4216", 150], ["A7003", 2], ["E1390", 1]])["flags"]
        by = {f["code"]: f for f in flags}
        assert by["A4216"]["over_limit"] and "A7003" not in by and by["E1390"]["prior_auth_required"]


def test_care_plan_costs_add_up():
    with trace.new_trace():
        c = billing.calculate_supply_costs("copd")
        assert c["lines"]
        assert round(sum(l["cost"] for l in c["lines"]), 2) == c["first_month_total"]
        assert c["one_time_total"] == 62.10


def test_similar_patients():
    with trace.new_trace():
        r = patients.find_similar_patients("65-year-old male with diabetes and hypertension")
        assert r["profile"]["age"] == 65 and r["profile"]["sex"] == "male"
        top = r["matches"][0]
        assert "Type 2 diabetes mellitus" in top["conditions"]
        r2 = patients.find_similar_patients(patient_id="P-0002")
        assert all(m["id"] != "P-0002" for m in r2["matches"])
