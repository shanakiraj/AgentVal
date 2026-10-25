"""Asynchronous evaluation runner.

Executes every test case of a dataset against an agent concurrently (bounded by an
``asyncio.Semaphore``), retries transient failures with exponential backoff + jitter,
scores outputs with the configured scorers, and aggregates run-level metrics.
"""

from __future__ import annotations

import asyncio
import inspect
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from agentval import stats
from agentval.agents.base import Agent, TraceRecorder, build_agent
from agentval.scorers import Scorer, ScoreResult, ScoringContext, build_scorer


def apply_scorer_preset(config: dict[str, Any], preset: str) -> dict[str, Any]:
    """Replace the config's scorers with a preset, keeping its LLM-judge settings (model, rubric, weight)."""
    judge = next((sp for sp in config.get("scorers", []) if isinstance(sp, dict) and sp.get("type") == "llm_judge"),
                 {"type": "llm_judge", "weight": 2, "params": {"model": "mock"}})
    core = [{"type": "exact_match", "params": {"field": "resolution"}}, {"type": "schema_match"}]
    presets = {
        "default": [*core, judge, {"type": "trajectory"}],
        "full": [*core, {"type": "contains"}, {"type": "groundedness"}, {"type": "safety", "weight": 2},
                 {"type": "trajectory"}, judge],
        "deterministic": [*core, {"type": "contains"}, {"type": "groundedness"}, {"type": "safety", "weight": 2},
                          {"type": "trajectory"}],
    }
    if preset not in presets:
        raise ValueError(f"Unknown scorer preset '{preset}' (choose from: {', '.join(presets)})")
    return {**config, "scorers": presets[preset]}



class EvalConfig(BaseModel):
    """Run configuration (also the ``--config`` JSON accepted by the CLI)."""

    name: str = "AgentVal run"
    agent: dict[str, Any] = Field(default_factory=lambda: {"type": "mock"})
    scorers: list[dict[str, Any] | str] = Field(
        default_factory=lambda: [
            {"type": "exact_match", "params": {"field": "resolution"}},
            {"type": "schema_match"},
            {"type": "llm_judge", "params": {"model": "mock"}},
            {"type": "trajectory"},
        ]
    )
    concurrency: int = Field(default=4, ge=1, le=256)
    trials: int = Field(default=1, ge=1, le=20, description="Repeat each case k times (pass@k, consistency)")
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_base_delay: float = Field(default=0.5, ge=0)
    retry_max_delay: float = Field(default=8.0, ge=0)
    timeout_s: float = Field(default=120.0, gt=0)
    pass_threshold: float = Field(default=0.7, ge=0, le=1)
    partial_threshold: float = Field(default=0.4, ge=0, le=1)


@dataclass
class CaseInput:
    id: str
    input: dict[str, Any]
    expected: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    name: str | None = None


@dataclass
class CaseOutcome:
    test_case_id: str
    actual: Any
    trace: dict[str, Any]
    score: float
    passed: bool
    status: str  # PASS | PARTIAL | FAIL | ERROR
    scores: dict[str, Any]
    latency_ms: int
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    attempts: int
    error: str | None = None
    metadata: dict[str, Any] | None = field(default=None)
    trial: int = 0


ResultCallback = Callable[[CaseOutcome, int, int], Awaitable[None] | None]


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """Exponential backoff with up to 25% jitter: base * 2**attempt, capped."""
    rng = rng or random
    return min(cap, base * (2**attempt)) * (1 + rng.random() * 0.25)


def classify(score: float, error: str | None, cfg: EvalConfig) -> tuple[bool, str]:
    if error:
        return False, "ERROR"
    if score >= cfg.pass_threshold:
        return True, "PASS"
    if score >= cfg.partial_threshold:
        return False, "PARTIAL"
    return False, "FAIL"


def aggregate(results: list[ScoreResult]) -> float:
    active = [r for r in results if not r.skipped]
    total_w = sum(r.weight for r in active)
    if not active or total_w <= 0:
        return 0.0
    return sum(r.score * r.weight for r in active) / total_w


async def _score_case(scorers: list[Scorer], ctx: ScoringContext) -> list[ScoreResult]:
    async def one(s: Scorer) -> ScoreResult:
        try:
            return await s.ascore(ctx)
        except Exception as exc:  # a broken scorer must not kill the run
            return ScoreResult(name=s.name, score=0.0, passed=False, rationale=f"Scorer error: {exc}",
                               weight=s.weight, details={"error": repr(exc)})

    return list(await asyncio.gather(*(one(s) for s in scorers)))


async def run_case(agent: Agent, scorers: list[Scorer], case: CaseInput, cfg: EvalConfig,
                   rng: random.Random | None = None, trial: int = 0) -> CaseOutcome:
    attempts = 0
    error: str | None = None
    actual: Any = None
    recorder = TraceRecorder()
    t0 = time.perf_counter()
    retry_log: list[dict[str, Any]] = []
    for attempt in range(cfg.max_retries + 1):
        attempts = attempt + 1
        recorder = TraceRecorder()
        try:
            actual = await asyncio.wait_for(agent.run(case.input, recorder), timeout=cfg.timeout_s)
            error = None
            break
        except Exception as exc:  # includes asyncio.TimeoutError
            error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            retry_log.append({"attempt": attempts, "error": error})
            if attempt < cfg.max_retries:
                await asyncio.sleep(backoff_delay(attempt, cfg.retry_base_delay, cfg.retry_max_delay, rng))
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if error:
        recorder.add_step("error", "agent_error", status="error", error=error,
                          attributes={"attempts": attempts})
        score_results: list[ScoreResult] = []
        score = 0.0
    else:
        ctx = ScoringContext(input=case.input, expected=case.expected, actual=actual,
                             trace={"steps": recorder.steps}, metadata=case.metadata)
        score_results = await _score_case(scorers, ctx)
        score = aggregate(score_results)

    passed, status = classify(score, error, cfg)
    trace = recorder.to_dict(attempts=attempts, total_latency_ms=latency_ms)
    if retry_log:
        trace["retries"] = retry_log
    return CaseOutcome(
        test_case_id=case.id,
        actual=actual,
        trace=trace,
        score=round(score, 4),
        passed=passed,
        status=status,
        scores={r.name: r.model_dump() for r in score_results},
        latency_ms=latency_ms,
        cost_usd=round(recorder.cost_usd, 8),
        prompt_tokens=recorder.prompt_tokens,
        completion_tokens=recorder.completion_tokens,
        attempts=attempts,
        error=error,
        metadata=case.metadata,
        trial=trial,
    )


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return float(s[idx])


def _case_tags(o: CaseOutcome) -> list[str]:
    meta = o.metadata or {}
    tags = [str(t) for t in meta.get("tags") or []]
    if meta.get("category"):
        tags.append(str(meta["category"]))
    return list(dict.fromkeys(tags))


def _breakdown(outcomes: list[CaseOutcome], key: Callable[[CaseOutcome], list[str]]) -> dict[str, Any]:
    groups: dict[str, list[CaseOutcome]] = {}
    for o in outcomes:
        for k in key(o):
            groups.setdefault(k, []).append(o)
    return {k: {"n": len(v), "passRate": round(sum(o.passed for o in v) / len(v), 4),
                "avgScore": round(statistics.fmean(o.score for o in v), 4)} for k, v in sorted(groups.items())}


def compute_metrics(outcomes: list[CaseOutcome], duration_ms: int | None = None) -> dict[str, Any]:
    n = len(outcomes)
    lat = [o.latency_ms for o in outcomes]
    counts = {s: sum(1 for o in outcomes if o.status == s) for s in ("PASS", "PARTIAL", "FAIL", "ERROR")}
    scorer_vals: dict[str, list[float]] = {}
    for o in outcomes:
        for name, r in o.scores.items():
            if not r.get("skipped"):
                scorer_vals.setdefault(name, []).append(r["score"])

    # Group repeated trials per case: case-level means feed the CIs (trials are not independent cases).
    by_case: dict[str, list[CaseOutcome]] = {}
    for o in outcomes:
        by_case.setdefault(o.test_case_id, []).append(o)
    case_scores = [statistics.fmean(x.score for x in g) for g in by_case.values()]
    trials = max((len(g) for g in by_case.values()), default=1)
    n_cases = len(by_case)
    case_pass = [sum(x.passed for x in g) for g in by_case.values()]
    metrics: dict[str, Any] = {
        "total": n,
        "cases": n_cases,
        "trials": trials,
        "passed": counts["PASS"],
        "partial": counts["PARTIAL"],
        "failed": counts["FAIL"],
        "errored": counts["ERROR"],
        "passRate": round(counts["PASS"] / n, 4) if n else 0.0,
        "passRateCi": list(stats.wilson_interval(counts["PASS"], n)),
        "avgScore": round(statistics.fmean(o.score for o in outcomes), 4) if n else 0.0,
        "avgScoreCi": list(stats.bootstrap_ci(case_scores)),
        "avgLatencyMs": round(statistics.fmean(lat), 1) if n else 0.0,
        "p50LatencyMs": _pct(lat, 0.5),
        "p95LatencyMs": _pct(lat, 0.95),
        "totalCostUsd": round(sum(o.cost_usd for o in outcomes), 8),
        "promptTokens": sum(o.prompt_tokens for o in outcomes),
        "completionTokens": sum(o.completion_tokens for o in outcomes),
        "tokenCount": sum(o.prompt_tokens + o.completion_tokens for o in outcomes),
        "totalRetries": sum(o.attempts - 1 for o in outcomes),
        "scorerAverages": {k: round(statistics.fmean(v), 4) for k, v in sorted(scorer_vals.items())},
        "tagBreakdown": _breakdown(outcomes, _case_tags),
        "difficultyBreakdown": _breakdown(
            outcomes, lambda o: [str((o.metadata or {})["difficulty"])] if (o.metadata or {}).get("difficulty") else []),
        "durationMs": duration_ms,
    }
    if trials > 1 and n_cases:
        sizes = [len(g) for g in by_case.values()]
        metrics["passAtK"] = round(statistics.fmean(stats.pass_at_k(sz, c, trials) for sz, c in zip(sizes, case_pass)), 4)
        metrics["passHatK"] = round(sum(1 for sz, c in zip(sizes, case_pass) if c == sz) / n_cases, 4)
        metrics["consistency"] = round(
            sum(1 for g in by_case.values() if len({x.status for x in g}) == 1) / n_cases, 4)
    return metrics


async def run_evaluation(
    cases: list[CaseInput],
    config: EvalConfig,
    *,
    agent: Agent | None = None,
    scorers: list[Scorer] | None = None,
    on_result: ResultCallback | None = None,
    seed: int | None = None,
) -> tuple[list[CaseOutcome], dict[str, Any]]:
    """Run all ``cases`` concurrently. ``on_result(outcome, done, total)`` fires as each completes."""
    agent = agent or build_agent(config.agent)
    scorers = scorers if scorers is not None else [build_scorer(s) for s in config.scorers]
    sem = asyncio.Semaphore(config.concurrency)
    rng = random.Random(seed)
    done = 0
    lock = asyncio.Lock()
    t0 = time.perf_counter()

    jobs = [(c, t) for t in range(config.trials) for c in cases]

    async def worker(case: CaseInput, trial: int) -> CaseOutcome:
        nonlocal done
        async with sem:
            outcome = await run_case(agent, scorers, case, config, rng, trial=trial)
        async with lock:
            done += 1
            if on_result is not None:
                res = on_result(outcome, done, len(jobs))
                if inspect.isawaitable(res):
                    await res
        return outcome

    outcomes = list(await asyncio.gather(*(worker(c, t) for c, t in jobs)))
    metrics = compute_metrics(outcomes, int((time.perf_counter() - t0) * 1000))
    return outcomes, metrics
