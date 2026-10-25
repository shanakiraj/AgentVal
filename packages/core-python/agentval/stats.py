"""Small, dependency-free statistics toolkit for evaluation results.

Eval datasets are small (often 5-200 cases), so point estimates alone are misleading.
Everything here is designed for that regime:

* :func:`wilson_interval` - confidence interval for a pass rate (well-behaved at 0% / 100%).
* :func:`bootstrap_ci` - percentile bootstrap CI for any statistic of case-level scores.
* :func:`paired_bootstrap` - paired test for "is run B better than run A on the same cases?".
* :func:`mcnemar_exact` - exact McNemar test on pass/fail flips between two runs.
* :func:`pass_at_k` - unbiased pass@k estimator (Chen et al., 2021) for repeated trials.

All randomness is seeded so reports are reproducible.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Callable, Sequence


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = statistics.fmean,
                 n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap confidence interval of ``stat(values)``."""
    vals = list(values)
    if not vals:
        return (0.0, 0.0)
    if len(vals) == 1:
        return (round(vals[0], 4), round(vals[0], 4))
    rng = random.Random(seed)
    n = len(vals)
    boots = sorted(stat([vals[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    lo = boots[int((alpha / 2) * (n_boot - 1))]
    hi = boots[int((1 - alpha / 2) * (n_boot - 1))]
    return (round(lo, 4), round(hi, 4))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n_boot: int = 4000, alpha: float = 0.05,
                     seed: int = 0) -> dict[str, float]:
    """Paired bootstrap over cases for the mean difference ``b - a``.

    Returns the observed mean delta, its CI and a two-sided p-value estimated as twice the
    fraction of bootstrap deltas on the other side of zero (clipped to 1).
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [y - x for x, y in zip(a, b)]
    if not diffs:
        return {"delta": 0.0, "ciLow": 0.0, "ciHigh": 0.0, "pValue": 1.0, "n": 0}
    observed = statistics.fmean(diffs)
    if all(abs(d) < 1e-12 for d in diffs):
        return {"delta": 0.0, "ciLow": 0.0, "ciHigh": 0.0, "pValue": 1.0, "n": len(diffs)}
    rng = random.Random(seed)
    n = len(diffs)
    boots = sorted(statistics.fmean([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    lo = boots[int((alpha / 2) * (n_boot - 1))]
    hi = boots[int((1 - alpha / 2) * (n_boot - 1))]
    if observed > 0:
        tail = sum(1 for x in boots if x <= 0) / n_boot
    else:
        tail = sum(1 for x in boots if x >= 0) / n_boot
    return {"delta": round(observed, 4), "ciLow": round(lo, 4), "ciHigh": round(hi, 4),
            "pValue": round(min(1.0, 2 * tail), 4), "n": n}


def mcnemar_exact(regressed: int, improved: int) -> float:
    """Two-sided exact McNemar p-value from discordant pass/fail pairs."""
    n = regressed + improved
    if n == 0:
        return 1.0
    k = min(regressed, improved)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return round(min(1.0, 2 * tail), 4)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimate of pass@k given ``n`` trials with ``c`` passes (Chen et al., 2021)."""
    if n <= 0 or k <= 0:
        return 0.0
    k = min(k, n)
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)
