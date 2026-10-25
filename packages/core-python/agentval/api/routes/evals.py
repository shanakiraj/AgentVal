from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from agentval import schemas, service
from agentval.db import get_session, session_scope
from agentval.models import TERMINAL_STATUSES, Dataset, EvalResult, EvalRun
from agentval.scorers import available_scorers

router = APIRouter(prefix="/api/v1/evals", tags=["evals"])

# Keep strong references to background tasks so they are not garbage-collected mid-run.
_TASKS: set[asyncio.Task] = set()


def _get_run(session: Session, run_id: str) -> EvalRun:
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


@router.get("/scorers", response_model=list[str])
def list_scorers():
    return available_scorers()


@router.post("/run", response_model=schemas.RunRead, status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(body: schemas.RunCreate, session: Session = Depends(get_session)):
    """Create a run and execute it asynchronously. Poll GET /runs/{id} or stream /runs/{id}/stream."""
    if session.get(Dataset, body.dataset_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    try:
        run = service.create_run(session, body.dataset_id, body.config, body.name)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False)) from exc
    task = asyncio.create_task(service.execute_run(run.id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return service.run_view(session, run)


@router.get("/runs", response_model=list[schemas.RunRead])
def list_runs(dataset_id: str | None = Query(None, alias="datasetId"), session: Session = Depends(get_session)):
    q = select(EvalRun).order_by(EvalRun.created_at.desc())
    if dataset_id:
        q = q.where(EvalRun.dataset_id == dataset_id)
    return [service.run_view(session, r) for r in session.exec(q).all()]


@router.get("/runs/{run_id}", response_model=schemas.RunDetail)
def get_run(run_id: str, include_traces: bool = Query(True, alias="includeTraces"),
            session: Session = Depends(get_session)):
    return service.run_detail(session, _get_run(session, run_id), include_traces)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, session: Session = Depends(get_session)):
    run = _get_run(session, run_id)
    if run.status not in TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Run is still in progress")
    session.delete(run)
    session.commit()


@router.get("/runs/{run_id}/results/{result_id}", response_model=schemas.ResultRead)
def get_result(run_id: str, result_id: str, session: Session = Depends(get_session)):
    r = session.get(EvalResult, result_id)
    if r is None or r.eval_run_id != run_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Result not found")
    return service.result_view(r, r.test_case)


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, interval: float = Query(0.5, ge=0.1, le=10)):
    """Server-Sent Events: ``progress`` events until the run reaches a terminal state, then ``done``."""
    with session_scope() as s:
        _get_run(s, run_id)

    async def events():
        last = None
        while True:
            if await request.is_disconnected():
                return
            with session_scope() as s:
                run = s.get(EvalRun, run_id)
                if run is None:
                    return
                view = service.run_view(s, run).model_dump(mode="json", by_alias=True)
            payload = {k: view[k] for k in ("id", "status", "completedCases", "totalCases", "progress", "metrics", "error")}
            if payload != last:
                yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
                last = payload
            if payload["status"] in TERMINAL_STATUSES:
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/runs/{run_id}/report")
def run_report(run_id: str, format: str = Query("md", pattern="^(md|csv|json)$"),
               session: Session = Depends(get_session)):
    """Download a run report as Markdown, CSV or JSON."""
    from agentval.reports import run_csv, run_markdown

    detail = service.run_detail(session, _get_run(session, run_id)).model_dump(mode="json", by_alias=True)
    if format == "json":
        return detail
    body, media, ext = ((run_markdown(detail), "text/markdown", "md") if format == "md"
                        else (run_csv(detail), "text/csv", "csv"))
    return PlainTextResponse(body, media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="agentval-{run_id[:8]}.{ext}"'})


def _policy(max_new_failures: int, max_score_drop: float, require_significance: bool, alpha: float):
    from agentval.regression import GatePolicy

    return GatePolicy(max_new_failures=max_new_failures, max_score_drop=max_score_drop,
                      require_significance=require_significance, alpha=alpha)


@router.get("/compare", response_model=schemas.CompareResponse)
def compare(run_a: str = Query(..., alias="runA"), run_b: str = Query(..., alias="runB"),
            max_new_failures: int = Query(0, alias="maxNewFailures", ge=0),
            max_score_drop: float = Query(0.02, alias="maxScoreDrop", ge=0),
            require_significance: bool = Query(False, alias="requireSignificance"),
            alpha: float = Query(0.05, gt=0, lt=1),
            session: Session = Depends(get_session)):
    """Metric deltas, per-case changes and a statistical regression analysis with a CI gate verdict."""
    return service.compare_runs(session, _get_run(session, run_a), _get_run(session, run_b),
                                _policy(max_new_failures, max_score_drop, require_significance, alpha))


@router.get("/compare/report", response_class=PlainTextResponse)
def compare_report(run_a: str = Query(..., alias="runA"), run_b: str = Query(..., alias="runB"),
                   session: Session = Depends(get_session)):
    """Markdown regression report, ready to paste into a pull-request comment."""
    from agentval.reports import compare_markdown

    a, b = _get_run(session, run_a), _get_run(session, run_b)
    res = service.compare_runs(session, a, b)
    return PlainTextResponse(compare_markdown(a.name, b.name, res.regression or {}), media_type="text/markdown")
