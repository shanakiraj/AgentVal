import math

import pytest

from agentval import stats


def test_wilson_interval_bounds_and_edges():
    assert stats.wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = stats.wilson_interval(5, 5)
    assert hi == 1.0 and 0.5 < lo < 0.6  # 100% on 5 cases is far from certain
    lo, hi = stats.wilson_interval(0, 5)
    assert lo == 0.0 and 0.4 < hi < 0.5
    lo, hi = stats.wilson_interval(50, 100)
    assert lo < 0.5 < hi and math.isclose(lo + hi, 1.0, abs_tol=1e-3)


def test_bootstrap_ci_contains_mean_and_is_reproducible():
    vals = [0.2, 0.4, 0.6, 0.8, 1.0, 0.9, 0.7]
    ci = stats.bootstrap_ci(vals)
    assert ci[0] <= sum(vals) / len(vals) <= ci[1]
    assert ci == stats.bootstrap_ci(vals)  # seeded
    assert stats.bootstrap_ci([]) == (0.0, 0.0)
    assert stats.bootstrap_ci([0.5]) == (0.5, 0.5)


def test_paired_bootstrap_detects_consistent_improvement():
    a = [0.5, 0.6, 0.4, 0.5, 0.55, 0.45, 0.5, 0.6]
    b = [x + 0.3 for x in a]
    res = stats.paired_bootstrap(a, b)
    assert res["delta"] == pytest.approx(0.3, abs=1e-4)
    assert res["ciLow"] > 0 and res["pValue"] < 0.05


def test_paired_bootstrap_identical_runs():
    res = stats.paired_bootstrap([1, 0.5], [1, 0.5])
    assert res["delta"] == 0 and res["pValue"] == 1.0


def test_paired_bootstrap_requires_equal_lengths():
    with pytest.raises(ValueError):
        stats.paired_bootstrap([1.0], [1.0, 0.5])


def test_mcnemar_exact():
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(0, 4) == 0.125  # 2 * 0.5**4
    assert stats.mcnemar_exact(0, 10) < 0.01
    assert stats.mcnemar_exact(3, 3) == 1.0


@pytest.mark.parametrize("n,c,k,expected", [(3, 0, 1, 0.0), (3, 3, 1, 1.0), (3, 1, 1, 1 / 3), (3, 1, 3, 1.0),
                                            (5, 2, 2, 1 - math.comb(3, 2) / math.comb(5, 2))])
def test_pass_at_k(n, c, k, expected):
    assert stats.pass_at_k(n, c, k) == pytest.approx(expected)
