from agentval.regression import GatePolicy, aggregate_cases, analyze


def r(tc, score, status=None, trial=0, name=None):
    status = status or ("PASS" if score >= 0.85 else "PARTIAL" if score >= 0.4 else "FAIL")
    return {"testCaseId": tc, "testCaseName": name or tc, "score": score, "status": status,
            "passed": status == "PASS", "trial": trial}


def test_aggregate_collapses_trials():
    agg = aggregate_cases([r("a", 1.0, trial=0), r("a", 0.5, trial=1), r("a", 1.0, trial=2), r("b", 0.2)])
    assert agg["a"].trials == 3 and agg["a"].score == round(2.5 / 3, 4)
    assert agg["a"].pass_rate == round(2 / 3, 4) and agg["a"].status == "PASS"
    assert agg["b"].status == "FAIL"


def test_regression_detected_and_gate_fails():
    a = [r(f"c{i}", 1.0) for i in range(6)]
    b = [r("c0", 0.3), r("c1", 0.5), *[r(f"c{i}", 1.0) for i in range(2, 6)]]
    rep = analyze(a, b)
    s = rep.summary
    assert s["newFailures"] == 2 and s["newPasses"] == 0 and s["regressed"] == 2 and s["unchanged"] == 4
    assert s["meanDelta"] < 0 and s["verdict"] in {"regression", "possible_regression"}
    assert rep.gate["passed"] is False and len(rep.gate["reasons"]) == 2
    flips = {c["testCaseId"]: c["flip"] for c in rep.cases}
    assert flips["c0"] == "broke" and flips["c2"] is None


def test_improvement_passes_gate():
    a = [r(f"c{i}", 0.5) for i in range(8)]
    b = [r(f"c{i}", 0.95) for i in range(8)]
    rep = analyze(a, b)
    assert rep.summary["verdict"] == "improvement" and rep.summary["newPasses"] == 8
    assert rep.gate["passed"] is True


def test_policy_tolerances_and_significance():
    a = [r("c0", 0.9), r("c1", 0.9), r("c2", 0.9)]
    b = [r("c0", 0.88), r("c1", 0.88), r("c2", 0.88)]
    assert analyze(a, b, GatePolicy(max_score_drop=0.05)).gate["passed"] is True
    assert analyze(a, b, GatePolicy(max_score_drop=0.0)).gate["passed"] is False
    noisy_a = [r("c0", 1.0), r("c1", 0.9)]
    noisy_b = [r("c0", 0.9), r("c1", 0.95)]
    assert analyze(noisy_a, noisy_b, GatePolicy(max_score_drop=0.0, require_significance=True)).gate["passed"] is True


def test_missing_cases_are_reported_not_paired():
    rep = analyze([r("a", 1.0), r("b", 1.0)], [r("a", 1.0), r("c", 1.0)])
    changes = {c["testCaseId"]: c["change"] for c in rep.cases}
    assert changes == {"a": "unchanged", "b": "missing", "c": "missing"}
    assert rep.summary["pairedCases"] == 1 and rep.summary["missing"] == 2


def test_empty_is_inconclusive():
    assert analyze([], []).summary["verdict"] == "inconclusive"
