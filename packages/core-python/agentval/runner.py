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

from agentval.agents.base import Agent, TraceRecorder, build_agent
from agentval.scorers import Scorer, ScoreResult, ScoringContext, build_scorer


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
                   rng: random.Random | None = None) -> CaseOutcome:
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
    )


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return float(s[idx])


def compute_metrics(outcomes: list[CaseOutcome], duration_ms: int | None = None) -> dict[str, Any]:
    n = len(outcomes)
    lat = [o.latency_ms for o in outcomes]
    counts = {s: sum(1 for o in outcomes if o.status == s) for s in ("PASS", "PARTIAL", "FAIL", "ERROR")}
    scorer_vals: dict[str, list[float]] = {}
    for o in outcomes:
        for name, r in o.scores.items():
            if not r.get("skipped"):
                scorer_vals.setdefault(name, []).append(r["score"])
    return {
        "total": n,
        "passed": counts["PASS"],
        "partial": counts["PARTIAL"],
        "failed": counts["FAIL"],
        "errored": counts["ERROR"],
        "passRate": round(counts["PASS"] / n, 4) if n else 0.0,
        "avgScore": round(statistics.fmean(o.score for o in outcomes), 4) if n else 0.0,
        "avgLatencyMs": round(statistics.fmean(lat), 1) if n else 0.0,
        "p50LatencyMs": _pct(lat, 0.5),
        "p95LatencyMs": _pct(lat, 0.95),
        "totalCostUsd": round(sum(o.cost_usd for o in outcomes), 8),
        "promptTokens": sum(o.prompt_tokens for o in outcomes),
        "completionTokens": sum(o.completion_tokens for o in outcomes),
        "tokenCount": sum(o.prompt_tokens + o.completion_tokens for o in outcomes),
        "totalRetries": sum(o.attempts - 1 for o in outcomes),
        "scorerAverages": {k: round(statistics.fmean(v), 4) for k, v in sorted(scorer_vals.items())},
        "durationMs": duration_ms,
    }


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

    async def worker(case: CaseInput) -> CaseOutcome:
        nonlocal done
        async with sem:
            outcome = await run_case(agent, scorers, case, config, rng)
        async with lock:
            done += 1
            if on_result is not None:
                res = on_result(outcome, done, len(cases))
                if inspect.isawaitable(res):
                    await res
        return outcome

    outcomes = list(await asyncio.gather(*(worker(c) for c in cases)))
    metrics = compute_metrics(outcomes, int((time.perf_counter() - t0) * 1000))
    return outcomes, metrics
