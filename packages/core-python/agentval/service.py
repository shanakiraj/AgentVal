"""Persistence-aware orchestration: create datasets, execute runs, build API views."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func
from sqlmodel import Session, select

from agentval.db import session_scope
from agentval.models import Dataset, EvalResult, EvalRun, RunStatus, TestCase, utcnow
from agentval.runner import CaseInput, CaseOutcome, EvalConfig, run_evaluation
from agentval import schemas

SAMPLE_DIR = Path(__file__).parent / "sample_data"
SAMPLE_DATASET = SAMPLE_DIR / "customer_service.json"


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
                  config=cfg.model_dump(), total_cases=n_cases)
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
            attempts=outcome.attempts, error=outcome.error))
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
        run.status, run.started_at, run.total_cases = RunStatus.RUNNING.value, utcnow(), len(cases)
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
        attempts=r.attempts, error=r.error)


def run_detail(session: Session, run: EvalRun, include_traces: bool = True) -> schemas.RunDetail:
    rows = session.exec(
        select(EvalResult, TestCase).join(TestCase, TestCase.id == EvalResult.test_case_id)
        .where(EvalResult.eval_run_id == run.id).order_by(TestCase.position, TestCase.created_at)).all()
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


def compare_runs(session: Session, run_a: EvalRun, run_b: EvalRun) -> schemas.CompareResponse:
    da, db = run_detail(session, run_a, False), run_detail(session, run_b, False)
    ma, mb = run_a.metrics or {}, run_b.metrics or {}
    metrics = [_delta(m, ma.get(m), mb.get(m)) for m in COMPARE_METRICS]
    scorer_names = sorted(set(ma.get("scorerAverages", {})) | set(mb.get("scorerAverages", {})))
    scorers = [_delta(n, ma.get("scorerAverages", {}).get(n), mb.get("scorerAverages", {}).get(n)) for n in scorer_names]

    by_a = {r.test_case_id: r for r in da.results}
    by_b = {r.test_case_id: r for r in db.results}
    names = {r.test_case_id: r.test_case_name for r in [*da.results, *db.results]}
    cases = []
    for tc_id in list(dict.fromkeys([*by_a, *by_b])):
        ra, rb = by_a.get(tc_id), by_b.get(tc_id)
        if ra and rb:
            d = round(rb.score - ra.score, 4)
            change = "improved" if d > 1e-9 else "regressed" if d < -1e-9 else "unchanged"
        else:
            d, change = None, "missing"
        cases.append(schemas.CaseComparison(
            test_case_id=tc_id, test_case_name=names.get(tc_id), status_a=ra.status if ra else None,
            status_b=rb.status if rb else None, score_a=ra.score if ra else None,
            score_b=rb.score if rb else None, delta=d, change=change))
    return schemas.CompareResponse(run_a=run_view(session, run_a), run_b=run_view(session, run_b),
                                   metrics=metrics, scorers=scorers, cases=cases)


# ----------------------------------------------------------------------------- seed
async def seed_sample(speed: float = 0.3) -> dict[str, Any]:
    """Create the sample dataset and two demo runs (baseline vs improved mock agent)."""
    with session_scope() as s:
        ds = import_dataset_file(s, SAMPLE_DATASET)
        ds_id = ds.id
        existing = s.exec(select(func.count()).select_from(EvalRun).where(EvalRun.dataset_id == ds_id)).one()
    run_ids = []
    if not existing:
        for cfg_name in ("mock-baseline", "mock-improved"):
            cfg = json.loads((SAMPLE_DIR / "configs" / f"{cfg_name}.json").read_text())
            cfg["agent"]["speed"] = speed
            with session_scope() as s:
                run = create_run(s, ds_id, cfg)
                run_ids.append(run.id)
            await execute_run(run.id)
    return {"datasetId": ds_id, "runIds": run_ids}
