"""Persistence-aware orchestration: create datasets, execute runs, build API views."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import func
from sqlmodel import Session, select

from agentval.db import session_scope
from agentval.models import Dataset, EvalResult, EvalRun, RunStatus, TestCase, utcnow
from agentval.runner import CaseInput, CaseOutcome, EvalConfig, compute_metrics, run_evaluation
from agentval import schemas

if TYPE_CHECKING:
    from agentval.regression import GatePolicy

SAMPLE_DIR = Path(__file__).parent / "sample_data"
SAMPLE_DATASET = SAMPLE_DIR / "customer_service.json"
# Bundled benchmark suite; usable as ``agentval run --dataset <key>``.
BUILTIN_DATASETS = {
    "sample": str(SAMPLE_DATASET),
    "customer-service": str(SAMPLE_DATASET),
    "rag": str(SAMPLE_DIR / "rag_grounded_qa.json"),
    "safety": str(SAMPLE_DIR / "safety_robustness.json"),
    "ops": str(SAMPLE_DIR / "multi_step_ops.json"),
}


# ----------------------------------------------------------------------------- datasets
def create_dataset(session: Session, data: schemas.DatasetCreate) -> Dataset:
    ds = Dataset(name=data.name, description=data.description)
    session.add(ds)
    session.flush()
    for i, tc in enumerate(data.test_cases):
        session.add(TestCase(dataset_id=ds.id, position=i, name=tc.name, input=tc.input, expected=tc.expected, meta=tc.metadata))
    session.commit()
    session.refresh(ds)
    return ds


def load_dataset_file(path: str | Path) -> schemas.DatasetCreate:
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, list):  # bare list of test cases
        raw = {"name": Path(path).stem, "testCases": raw}
    return schemas.DatasetCreate.model_validate(raw)


def import_dataset_file(session: Session, path: str | Path, reuse: bool = True) -> Dataset:
    """Import a dataset JSON file; with ``reuse`` an existing dataset of the same name is returned."""
    data = load_dataset_file(path)
    if reuse:
        existing = session.exec(select(Dataset).where(Dataset.name == data.name)).first()
        if existing:
            return existing
    return create_dataset(session, data)


def add_test_cases(session: Session, ds: Dataset, items: list[schemas.TestCaseCreate]) -> list[TestCase]:
    start = session.exec(select(func.coalesce(func.max(TestCase.position), -1)).where(TestCase.dataset_id == ds.id)).one() + 1
    created = [TestCase(dataset_id=ds.id, position=start + i, name=tc.name, input=tc.input,
                        expected=tc.expected, meta=tc.metadata) for i, tc in enumerate(items)]
    session.add_all(created)
    ds.updated_at = utcnow()
    session.add(ds)
    session.commit()
    for tc in created:
        session.refresh(tc)
    return created


def test_case_view(tc: TestCase) -> schemas.TestCaseRead:
    return schemas.TestCaseRead(id=tc.id, dataset_id=tc.dataset_id, name=tc.name, input=tc.input,
                                expected=tc.expected, metadata=tc.meta, created_at=tc.created_at)


def dataset_view(session: Session, ds: Dataset, detail: bool = False) -> schemas.DatasetRead:
    n_cases = session.exec(select(func.count()).select_from(TestCase).where(TestCase.dataset_id == ds.id)).one()
    n_runs = session.exec(select(func.count()).select_from(EvalRun).where(EvalRun.dataset_id == ds.id)).one()
    base = dict(id=ds.id, name=ds.name, description=ds.description, created_at=ds.created_at,
                updated_at=ds.updated_at, test_case_count=n_cases, run_count=n_runs)
    if not detail:
        return schemas.DatasetRead(**base)
    cases = session.exec(select(TestCase).where(TestCase.dataset_id == ds.id).order_by(TestCase.position, TestCase.created_at)).all()
    return schemas.DatasetDetail(**base, test_cases=[test_case_view(c) for c in cases])


# ----------------------------------------------------------------------------- runs
def create_run(session: Session, dataset_id: str, config: dict[str, Any], name: str | None = None) -> EvalRun:
    cfg = EvalConfig.model_validate({**config, **({"name": name} if name else {})})
    n_cases = session.exec(select(func.count()).select_from(TestCase).where(TestCase.dataset_id == dataset_id)).one()
    run = EvalRun(dataset_id=dataset_id, name=cfg.name, status=RunStatus.PENDING.value,
                  model=cfg.agent.get("model") or cfg.agent.get("type"),
                  config=cfg.model_dump(), total_cases=n_cases * cfg.trials)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _save_outcome(run_id: str, outcome: CaseOutcome, done: int) -> None:
    with session_scope() as s:
        s.add(EvalResult(
            eval_run_id=run_id, test_case_id=outcome.test_case_id, actual=outcome.actual,
            trace=outcome.trace, score=outcome.score, passed=outcome.passed, status=outcome.status,
            scores=outcome.scores, latency_ms=outcome.latency_ms, cost_usd=outcome.cost_usd,
            prompt_tokens=outcome.prompt_tokens, completion_tokens=outcome.completion_tokens,
            attempts=outcome.attempts, trial=outcome.trial, error=outcome.error))
        run = s.get(EvalRun, run_id)
        if run:
            run.completed_cases = done
            s.add(run)
        s.commit()


def _on_result(run_id: str, o: CaseOutcome, done: int, total: int, progress: Any) -> None:
    _save_outcome(run_id, o, done)
    if progress is not None:
        progress(o, done, total)


async def execute_run(run_id: str, progress: Callable[[CaseOutcome, int, int], None] | None = None) -> EvalRun:
    """Execute a PENDING run, persisting each result as it completes (enables live progress)."""
    with session_scope() as s:
        run = s.get(EvalRun, run_id)
        if run is None:
            raise KeyError(run_id)
        cfg = EvalConfig.model_validate(run.config)
        cases = [CaseInput(id=tc.id, input=tc.input, expected=tc.expected, metadata=tc.meta, name=tc.name)
                 for tc in s.exec(select(TestCase).where(TestCase.dataset_id == run.dataset_id).order_by(TestCase.position, TestCase.created_at)).all()]
        run.status, run.started_at, run.total_cases = RunStatus.RUNNING.value, utcnow(), len(cases) * cfg.trials
        s.add(run)
        s.commit()

    try:
        _, metrics = await run_evaluation(cases, cfg, on_result=lambda o, d, t: _on_result(run_id, o, d, t, progress))
        status, error = RunStatus.COMPLETED.value, None
    except Exception as exc:  # configuration errors, unknown scorer, etc.
        metrics, status, error = None, RunStatus.FAILED.value, f"{type(exc).__name__}: {exc}"

    with session_scope() as s:
        run = s.get(EvalRun, run_id)
        assert run is not None
        run.status, run.metrics, run.error, run.finished_at = status, metrics, error, utcnow()
        s.add(run)
        s.commit()
        s.refresh(run)
        return run


def run_view(session: Session, run: EvalRun) -> schemas.RunRead:
    ds = session.get(Dataset, run.dataset_id)
    progress = (run.completed_cases / run.total_cases) if run.total_cases else (1.0 if run.status == "COMPLETED" else 0.0)
    return schemas.RunRead(
        id=run.id, dataset_id=run.dataset_id, dataset_name=ds.name if ds else None, name=run.name,
        status=run.status, model=run.model, config=run.config, metrics=run.metrics,
        total_cases=run.total_cases, completed_cases=run.completed_cases, progress=round(progress, 4),
        error=run.error, created_at=run.created_at, started_at=run.started_at, finished_at=run.finished_at)


def result_view(r: EvalResult, tc: TestCase | None, include_trace: bool = True) -> schemas.ResultRead:
    return schemas.ResultRead(
        id=r.id, eval_run_id=r.eval_run_id, test_case_id=r.test_case_id,
        test_case_name=tc.name if tc else None, input=tc.input if tc else None,
        expected=tc.expected if tc else None, actual=r.actual, trace=r.trace if include_trace else None,
        score=r.score, passed=r.passed, status=r.status, scores=r.scores, latency_ms=r.latency_ms,
        cost_usd=r.cost_usd, prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
        attempts=r.attempts, trial=r.trial, error=r.error)


def run_detail(session: Session, run: EvalRun, include_traces: bool = True) -> schemas.RunDetail:
    rows = session.exec(
        select(EvalResult, TestCase).join(TestCase, TestCase.id == EvalResult.test_case_id)
        .where(EvalResult.eval_run_id == run.id).order_by(TestCase.position, TestCase.created_at, EvalResult.trial)).all()
    return schemas.RunDetail(**run_view(session, run).model_dump(),
                             results=[result_view(r, tc, include_traces) for r, tc in rows])


# ----------------------------------------------------------------------------- compare
LOWER_IS_BETTER = {"avgLatencyMs", "p95LatencyMs", "totalCostUsd", "tokenCount", "failed", "errored", "totalRetries"}
COMPARE_METRICS = ["passRate", "avgScore", "passed", "partial", "failed", "errored", "avgLatencyMs",
                   "p95LatencyMs", "totalCostUsd", "tokenCount", "totalRetries"]


def _delta(metric: str, a: float | None, b: float | None) -> schemas.MetricDelta:
    if a is None or b is None:
        return schemas.MetricDelta(metric=metric, a=a, b=b)
    d = round(b - a, 6)
    if abs(d) < 1e-9:
        better = "same"
    else:
        better = ("b" if d < 0 else "a") if metric in LOWER_IS_BETTER else ("b" if d > 0 else "a")
    return schemas.MetricDelta(metric=metric, a=a, b=b, delta=d, better=better)


def compare_runs(session: Session, run_a: EvalRun, run_b: EvalRun,
                 policy: "GatePolicy | None" = None) -> schemas.CompareResponse:
    from agentval.regression import analyze

    da, db = run_detail(session, run_a, False), run_detail(session, run_b, False)
    ma, mb = run_a.metrics or {}, run_b.metrics or {}
    metrics = [_delta(m, ma.get(m), mb.get(m)) for m in COMPARE_METRICS]
    scorer_names = sorted(set(ma.get("scorerAverages", {})) | set(mb.get("scorerAverages", {})))
    scorers = [_delta(n, ma.get("scorerAverages", {}).get(n), mb.get("scorerAverages", {}).get(n)) for n in scorer_names]

    report = analyze(da.results, db.results, policy)
    cases = [schemas.CaseComparison(
        test_case_id=c["testCaseId"], test_case_name=c["testCaseName"], status_a=c["statusA"], status_b=c["statusB"],
        score_a=c["scoreA"], score_b=c["scoreB"], delta=c["delta"], change=c["change"]) for c in report.cases]
    return schemas.CompareResponse(run_a=run_view(session, run_a), run_b=run_view(session, run_b),
                                   metrics=metrics, scorers=scorers, cases=cases,
                                   regression={"summary": report.summary, "gate": report.gate,
                                               "cases": report.cases})


def recompute_metrics(session: Session, run: EvalRun) -> dict[str, Any]:
    """Recompute run metrics from stored results (e.g. after upgrading the metrics schema)."""
    rows = session.exec(select(EvalResult, TestCase).join(TestCase, TestCase.id == EvalResult.test_case_id)
                        .where(EvalResult.eval_run_id == run.id)).all()
    outcomes = [CaseOutcome(test_case_id=r.test_case_id, actual=r.actual, trace=r.trace, score=r.score,
                            passed=r.passed, status=r.status, scores=r.scores, latency_ms=r.latency_ms,
                            cost_usd=r.cost_usd, prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
                            attempts=r.attempts, error=r.error, metadata=tc.meta, trial=r.trial) for r, tc in rows]
    duration = (run.metrics or {}).get("durationMs")
    run.metrics = compute_metrics(outcomes, duration)
    session.add(run)
    session.commit()
    return run.metrics


async def rescore_run(run_id: str, preset: str | None = None) -> EvalRun:
    """Re-apply scorers to stored outputs and traces without re-running the agent.

    Use it after improving a scorer or to add new scorers to historical runs. LLM-judge verdicts
    already stored are reused (no new API calls); other scorers are recomputed.
    """
    from agentval.runner import _score_case, aggregate, apply_scorer_preset, classify
    from agentval.scorers import ScoreResult, ScoringContext, build_scorer

    with session_scope() as s:
        run = s.get(EvalRun, run_id)
        if run is None:
            raise KeyError(run_id)
        config = apply_scorer_preset(run.config, preset) if preset else run.config
        cfg = EvalConfig.model_validate(config)
        rows = s.exec(select(EvalResult, TestCase).join(TestCase, TestCase.id == EvalResult.test_case_id)
                      .where(EvalResult.eval_run_id == run_id)).all()
        specs = [sp if isinstance(sp, dict) else {"type": sp} for sp in cfg.scorers]
        for r, tc in rows:
            if r.error:
                continue
            reuse = {name: v for name, v in (r.scores or {}).items()
                     if name == "llm_judge" and not (v.get("details") or {}).get("judge") == "mock"}
            todo = [build_scorer(sp) for sp in specs if not (sp["type"] in reuse)]
            ctx = ScoringContext(input=tc.input, expected=tc.expected, actual=r.actual, trace=r.trace, metadata=tc.meta)
            fresh = await _score_case(todo, ctx)
            kept = []
            for sp in specs:
                if sp["type"] in reuse:
                    res = ScoreResult.model_validate(reuse[sp["type"]])
                    res.weight = float(sp.get("weight", res.weight))
                    kept.append(res)
            results = fresh + kept
            order = {sp["type"]: i for i, sp in enumerate(specs)}
            results.sort(key=lambda x: order.get(x.name, 99))
            r.score = round(aggregate(results), 4)
            r.passed, r.status = classify(r.score, None, cfg)
            r.scores = {x.name: x.model_dump() for x in results}
            s.add(r)
        run.config = cfg.model_dump()
        s.add(run)
        s.commit()
        recompute_metrics(s, run)
        s.refresh(run)
        return run


# ----------------------------------------------------------------------------- bundles
def _dt(value: Any) -> Any:
    from datetime import datetime

    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def import_bundle(session: Session, bundle: dict[str, Any]) -> dict[str, int]:
    """Import an ``agentval export-demo`` bundle, preserving ids (idempotent: existing ids are skipped).

    This makes results portable: runs produced on one machine (e.g. a slow, rate-limited sweep of
    free models) can be merged into another database without re-running anything.
    """
    counts = {"datasets": 0, "testCases": 0, "runs": 0, "results": 0}
    for d in bundle.get("datasets", []):
        if session.get(Dataset, d["id"]) is None:
            session.add(Dataset(id=d["id"], name=d["name"], description=d.get("description"),
                                created_at=_dt(d["createdAt"]), updated_at=_dt(d["updatedAt"])))
            counts["datasets"] += 1
        for i, tc in enumerate(d.get("testCases", [])):
            if session.get(TestCase, tc["id"]) is None:
                session.add(TestCase(id=tc["id"], dataset_id=d["id"], position=i, name=tc.get("name"),
                                     input=tc["input"], expected=tc.get("expected"), meta=tc.get("metadata"),
                                     created_at=_dt(tc["createdAt"])))
                counts["testCases"] += 1
    session.flush()
    for r in bundle.get("runs", []):
        if session.get(EvalRun, r["id"]) is not None:
            continue
        session.add(EvalRun(id=r["id"], dataset_id=r["datasetId"], name=r["name"], status=r["status"],
                            model=r.get("model"), config=r.get("config") or {}, metrics=r.get("metrics"),
                            total_cases=r.get("totalCases", 0), completed_cases=r.get("completedCases", 0),
                            error=r.get("error"), created_at=_dt(r["createdAt"]), started_at=_dt(r.get("startedAt")),
                            finished_at=_dt(r.get("finishedAt"))))
        counts["runs"] += 1
        session.flush()
        for res in r.get("results", []):
            session.add(EvalResult(
                id=res["id"], eval_run_id=r["id"], test_case_id=res["testCaseId"], actual=res.get("actual"),
                trace=res.get("trace") or {}, score=res["score"], passed=res["passed"], status=res["status"],
                scores=res.get("scores") or {}, latency_ms=res.get("latencyMs", 0), cost_usd=res.get("costUsd", 0.0),
                prompt_tokens=res.get("promptTokens", 0), completion_tokens=res.get("completionTokens", 0),
                attempts=res.get("attempts", 1), error=res.get("error"), trial=res.get("trial", 0)))
            counts["results"] += 1
    session.commit()
    return counts


# ----------------------------------------------------------------------------- seed
SUITE = ("rag", "safety", "ops")


async def seed_sample(speed: float = 1.0, suite: bool = True) -> dict[str, Any]:
    """Create the sample dataset and two demo runs (baseline vs improved mock agent).

    With ``suite`` the benchmark suite (RAG, safety, multi-step ops) is seeded too, each with a
    baseline and an improved mock run using the full scorer preset and 3 trials per case.
    """
    from agentval.runner import apply_scorer_preset

    plan: list[tuple[str, int, str | None]] = [(str(SAMPLE_DATASET), 1, None)]
    if suite:
        plan += [(BUILTIN_DATASETS[k], 3, "full") for k in SUITE]
    dataset_ids, run_ids = [], []
    for path, trials, preset in plan:
        with session_scope() as s:
            ds = import_dataset_file(s, path)
            ds_id = ds.id
            existing = s.exec(select(func.count()).select_from(EvalRun).where(EvalRun.dataset_id == ds_id)).one()
        dataset_ids.append(ds_id)
        if existing:
            continue
        for cfg_name in ("mock-baseline", "mock-improved"):
            cfg = json.loads((SAMPLE_DIR / "configs" / f"{cfg_name}.json").read_text())
            cfg["agent"]["speed"] = speed
            cfg["trials"] = trials
            if preset:
                cfg = apply_scorer_preset(cfg, preset)
            with session_scope() as s:
                run = create_run(s, ds_id, cfg)
                run_ids.append(run.id)
            await execute_run(run.id)
    return {"datasetId": dataset_ids[0], "datasetIds": dataset_ids, "runIds": run_ids}
