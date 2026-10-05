import json

from cds.eval.harness import GOLD, run, unsafe_reasons


def test_gold_set_shape():
    qs = json.loads(GOLD.read_text())["questions"]
    assert len(qs) == 50 and len({q["id"] for q in qs}) == 50


def test_all_prd_targets_met_offline():
    res = run()
    missed = [m["name"] for m in res["metrics"] if not m["passed"]]
    assert not missed, (missed, res["failures"])


def test_unsafe_detector():
    assert unsafe_reasons("Use code Q1234 at $9.99") == ["unknown code Q1234", "unsupported amount $9.99"]
    assert unsafe_reasons("A4216 costs $0.41") == []
