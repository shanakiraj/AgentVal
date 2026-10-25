"""Run-vs-run regression analysis and CI gating.

Works on plain result records (from the database, an ``agentval run -o`` file or an export
bundle), so the same logic powers the API, the web compare view and ``agentval compare``.

Repeated trials are collapsed per test case first (mean score, pass fraction), because the
case - not the trial - is the unit of independent evidence.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable

from agentval import stats


def _get(r: Any, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if isinstance(r, dict) and k in r:
            return r[k]
        if not isinstance(r, dict) and hasattr(r, k):
            return getattr(r, k)
    return default


@dataclass
class CaseAggregate:
    test_case_id: str
    name: str | None
    score: float
    pass_rate: float
    status: str
    trials: int


def aggregate_cases(results: Iterable[Any]) -> dict[str, CaseAggregate]:
    groups: dict[str, list[Any]] = {}
    for r in results:
        groups.setdefault(str(_get(r, "test_case_id", "testCaseId")), []).append(r)
    out = {}
    for tc_id, rs in groups.items():
        statuses = [str(_get(r, "status", default="FAIL")) for r in rs]
        out[tc_id] = CaseAggregate(
            test_case_id=tc_id,
            name=_get(rs[0], "test_case_name", "testCaseName"),
            score=round(statistics.fmean(float(_get(r, "score", default=0.0)) for r in rs), 4),
            pass_rate=round(sum(1 for r in rs if _get(r, "passed", default=False)) / len(rs), 4),
            status=max(set(statuses), key=lambda s: (statuses.count(s), s == "PASS")),
            trials=len(rs),
        )
    return out


@dataclass
class GatePolicy:
    """Thresholds for ``--fail-on-regression``."""

    max_new_failures: int = 0          # cases that passed in A but not in B
    max_score_drop: float = 0.02       # allowed drop in mean case score
    require_significance: bool = False  # only fail a score drop if p < alpha
    alpha: float = 0.05


@dataclass
class RegressionReport:
    cases: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"cases": self.cases, "summary": self.summary, "gate": self.gate}


def analyze(results_a: Iterable[Any], results_b: Iterable[Any], policy: GatePolicy | None = None,
            eps: float = 1e-9) -> RegressionReport:
    policy = policy or GatePolicy()
    a, b = aggregate_cases(results_a), aggregate_cases(results_b)
    cases: list[dict[str, Any]] = []
    paired_a: list[float] = []
    paired_b: list[float] = []
    new_failures = new_passes = 0
    for tc_id in dict.fromkeys([*a, *b]):
        ca, cb = a.get(tc_id), b.get(tc_id)
        row: dict[str, Any] = {"testCaseId": tc_id, "testCaseName": (ca or cb).name if (ca or cb) else None,
                               "scoreA": ca.score if ca else None, "scoreB": cb.score if cb else None,
                               "statusA": ca.status if ca else None, "statusB": cb.status if cb else None,
                               "passRateA": ca.pass_rate if ca else None, "passRateB": cb.pass_rate if cb else None}
        if ca and cb:
            d = round(cb.score - ca.score, 4)
            row["delta"] = d
            row["change"] = "improved" if d > eps else "regressed" if d < -eps else "unchanged"
            was, now = ca.pass_rate >= 0.5, cb.pass_rate >= 0.5
            row["flip"] = "fixed" if (not was and now) else "broke" if (was and not now) else None
            new_failures += row["flip"] == "broke"
            new_passes += row["flip"] == "fixed"
            paired_a.append(ca.score)
            paired_b.append(cb.score)
        else:
            row["delta"], row["change"], row["flip"] = None, "missing", None
        cases.append(row)

    boot = stats.paired_bootstrap(paired_a, paired_b)
    mcnemar = stats.mcnemar_exact(new_failures, new_passes)
    significant = boot["pValue"] < policy.alpha and boot["n"] >= 3
    if boot["n"] == 0:
        verdict = "inconclusive"
    elif significant and boot["delta"] < 0:
        verdict = "regression"
    elif significant and boot["delta"] > 0:
        verdict = "improvement"
    elif new_failures and not new_passes:
        verdict = "possible_regression"
    elif new_passes and not new_failures:
        verdict = "possible_improvement"
    else:
        verdict = "no_significant_change"

    summary = {
        "pairedCases": boot["n"],
        "improved": sum(c["change"] == "improved" for c in cases),
        "regressed": sum(c["change"] == "regressed" for c in cases),
        "unchanged": sum(c["change"] == "unchanged" for c in cases),
        "missing": sum(c["change"] == "missing" for c in cases),
        "newFailures": new_failures,
        "newPasses": new_passes,
        "meanDelta": boot["delta"],
        "ci95": [boot["ciLow"], boot["ciHigh"]],
        "pValue": boot["pValue"],
        "mcnemarP": mcnemar,
        "verdict": verdict,
    }
    reasons = []
    if new_failures > policy.max_new_failures:
        reasons.append(f"{new_failures} case(s) went from pass to fail (allowed: {policy.max_new_failures})")
    if boot["delta"] < -policy.max_score_drop and (not policy.require_significance or significant):
        reasons.append(f"mean case score dropped {abs(boot['delta']):.3f} (allowed: {policy.max_score_drop:.3f})")
    gate = {"passed": not reasons, "reasons": reasons,
            "policy": {"maxNewFailures": policy.max_new_failures, "maxScoreDrop": policy.max_score_drop,
                       "requireSignificance": policy.require_significance, "alpha": policy.alpha}}
    return RegressionReport(cases=cases, summary=summary, gate=gate)
