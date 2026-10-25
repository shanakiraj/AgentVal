"""``agentval`` command-line interface.

  agentval run --dataset <path|id|sample> --config <config.json|mock-baseline|mock-improved>
  agentval seed            # sample dataset + two demo runs
  agentval serve           # start the FastAPI server
  agentval export-demo     # dump datasets/runs as JSON (static demo data for the web app)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from agentval.service import SAMPLE_DATASET, SAMPLE_DIR

STATUS_COLORS = {"PASS": "\033[32m", "PARTIAL": "\033[33m", "FAIL": "\033[31m", "ERROR": "\033[35m"}
RESET = "\033[0m"


def _color(status: str, use: bool) -> str:
    return f"{STATUS_COLORS.get(status, '')}{status}{RESET}" if use else status


def _resolve_config(value: str | None) -> dict[str, Any]:
    if not value:
        return json.loads((SAMPLE_DIR / "configs" / "mock-improved.json").read_text())
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text())
    builtin = SAMPLE_DIR / "configs" / f"{value}.json"
    if builtin.exists():
        return json.loads(builtin.read_text())
    raise SystemExit(f"Config not found: {value} (path or one of: "
                     f"{', '.join(p.stem for p in (SAMPLE_DIR / 'configs').glob('*.json'))})")


def _setup_db(url: str | None) -> None:
    from agentval.db import init_db, make_engine, set_engine

    if url:
        os.environ["DATABASE_URL"] = url
    set_engine(make_engine(os.environ.get("DATABASE_URL", "sqlite:///./agentval.db")))
    init_db()


def _print_summary(name: str, metrics: dict[str, Any], rows: list[tuple[str, str, float, int, int]], color: bool) -> None:
    print(f"\n{'Test case':<36} {'Status':<8} {'Score':>6} {'Latency':>9} {'Tries':>5}")
    print("-" * 68)
    for case, st, score, lat, tries in rows:
        pad = 8 + (len(_color(st, color)) - len(st))
        print(f"{(case or '')[:36]:<36} {_color(st, color):<{pad}} {score:>6.3f} {lat:>7}ms {tries:>5}")
    print("-" * 68)
    print(f"Run: {name}")
    print(f"  pass rate     {metrics['passRate']:.0%}  ({metrics['passed']} pass / {metrics['partial']} partial / "
          f"{metrics['failed']} fail / {metrics['errored']} error)")
    print(f"  avg score     {metrics['avgScore']:.3f}")
    print(f"  avg latency   {metrics['avgLatencyMs']:.0f} ms   (p95 {metrics['p95LatencyMs']:.0f} ms)")
    print(f"  total cost    ${metrics['totalCostUsd']:.6f}   tokens {metrics['tokenCount']}")
    print(f"  retries       {metrics['totalRetries']}")
    print("  scorers       " + ", ".join(f"{k}={v:.3f}" for k, v in metrics["scorerAverages"].items()))


def cmd_run(args: argparse.Namespace) -> int:
    from agentval.runner import CaseInput, EvalConfig, run_evaluation
    from agentval.service import load_dataset_file

    config = _resolve_config(args.config)
    if args.concurrency:
        config["concurrency"] = args.concurrency
    if args.name:
        config["name"] = args.name
    color = sys.stdout.isatty() and not args.no_color
    dataset_arg = str(SAMPLE_DATASET) if args.dataset == "sample" else args.dataset
    is_file = Path(dataset_arg).exists()

    def progress(o, done, total):
        if not args.quiet:
            print(f"  [{done}/{total}] {_color(o.status, color)} score={o.score:.3f} {o.latency_ms}ms", flush=True)

    if args.no_persist:
        if not is_file:
            raise SystemExit("--no-persist requires --dataset to be a JSON file")
        data = load_dataset_file(dataset_arg)
        cases = [CaseInput(id=str(i), input=c.input, expected=c.expected, metadata=c.metadata, name=c.name)
                 for i, c in enumerate(data.test_cases)]
        cfg = EvalConfig.model_validate(config)
        print(f"Running '{cfg.name}' on '{data.name}' ({len(cases)} cases, concurrency {cfg.concurrency})")
        outcomes, metrics = asyncio.run(run_evaluation(cases, cfg, on_result=progress))
        names = {str(i): c.name for i, c in enumerate(data.test_cases)}
        rows = [(names[o.test_case_id], o.status, o.score, o.latency_ms, o.attempts) for o in outcomes]
        _print_summary(cfg.name, metrics, rows, color)
        if args.output:
            Path(args.output).write_text(json.dumps({"metrics": metrics, "results": [o.__dict__ for o in outcomes]},
                                                    indent=2, default=str))
        return 0 if metrics["errored"] == 0 else 1

    _setup_db(args.db)
    from agentval.db import session_scope
    from agentval.models import Dataset
    from agentval.service import create_run, execute_run, import_dataset_file, run_detail

    with session_scope() as s:
        if is_file:
            ds = import_dataset_file(s, dataset_arg)
        else:
            ds = s.get(Dataset, dataset_arg)
            if ds is None:
                raise SystemExit(f"Dataset not found: {dataset_arg} (pass a JSON file path, dataset id or 'sample')")
        run = create_run(s, ds.id, config)
        print(f"Running '{run.name}' on '{ds.name}' ({run.total_cases} cases) -> run {run.id}")
    run = asyncio.run(execute_run(run.id, progress))
    if run.status != "COMPLETED":
        print(f"Run FAILED: {run.error}", file=sys.stderr)
        return 2
    with session_scope() as s:
        detail = run_detail(s, run, include_traces=bool(args.output))
    rows = [(r.test_case_name, r.status, r.score, r.latency_ms, r.attempts) for r in detail.results]
    _print_summary(run.name, run.metrics or {}, rows, color)
    print(f"\nRun id: {run.id}")
    if args.output:
        Path(args.output).write_text(detail.model_dump_json(by_alias=True, indent=2))
        print(f"Wrote {args.output}")
    return 0 if (run.metrics or {}).get("errored", 0) == 0 else 1


def cmd_seed(args: argparse.Namespace) -> int:
    _setup_db(args.db)
    from agentval.service import seed_sample

    print(json.dumps(asyncio.run(seed_sample(speed=args.speed)), indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    if args.db:
        os.environ["DATABASE_URL"] = args.db
    uvicorn.run("agentval.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_export_demo(args: argparse.Namespace) -> int:
    """Export everything (datasets with test cases, runs with results + traces) to a JSON file."""
    _setup_db(args.db)
    from sqlmodel import select

    from agentval.db import session_scope
    from agentval.models import Dataset, EvalRun
    from agentval.service import dataset_view, run_detail

    with session_scope() as s:
        datasets = [dataset_view(s, d, detail=True).model_dump(mode="json", by_alias=True)
                    for d in s.exec(select(Dataset).order_by(Dataset.created_at.desc())).all()]
        runs = [run_detail(s, r).model_dump(mode="json", by_alias=True)
                for r in s.exec(select(EvalRun).order_by(EvalRun.created_at.desc())).all()]
    out = {"generatedBy": "agentval export-demo", "datasets": datasets, "runs": runs}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"Exported {len(datasets)} dataset(s) and {len(runs)} run(s) to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentval", description="AgentVal - evaluate multi-step AI agents")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run an evaluation from the terminal")
    r.add_argument("--dataset", required=True, help="Dataset JSON path, dataset id in the DB, or 'sample'")
    r.add_argument("--config", help="Config JSON path or built-in name (mock-baseline, mock-improved, litellm-openai)")
    r.add_argument("--name", help="Override run name")
    r.add_argument("--concurrency", type=int)
    r.add_argument("--db", help="Database URL (default: $DATABASE_URL or sqlite:///./agentval.db)")
    r.add_argument("--no-persist", action="store_true", help="Run in-memory without writing to the database")
    r.add_argument("--output", "-o", help="Write full results (incl. traces) as JSON")
    r.add_argument("--quiet", "-q", action="store_true")
    r.add_argument("--no-color", action="store_true")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("seed", help="Load the sample dataset and create two demo runs")
    s.add_argument("--db")
    s.add_argument("--speed", type=float, default=1.0, help="Mock agent latency multiplier")
    s.set_defaults(func=cmd_seed)

    v = sub.add_parser("serve", help="Start the API server")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--reload", action="store_true")
    v.add_argument("--db")
    v.set_defaults(func=cmd_serve)

    e = sub.add_parser("export-demo", help="Export datasets and runs as static JSON")
    e.add_argument("--output", "-o", default="demo-data.json")
    e.add_argument("--db")
    e.set_defaults(func=cmd_export_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
