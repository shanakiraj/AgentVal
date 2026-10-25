"""``agentval`` command-line interface.

  agentval run --dataset <path|id|sample> --config <config.json|mock-baseline|mock-improved>
  agentval seed            # sample dataset + two demo runs
  agentval serve           # start the FastAPI server
  agentval compare A B --fail-on-regression   # statistical run-vs-run diff + CI gate (exit 1)
  agentval report RUN --format md|csv|json    # shareable run report
  agentval export-demo     # dump datasets/runs as JSON (static demo data for the web app)
  agentval import FILE...  # merge export bundles into a database (ids preserved)
  agentval rescore RUN...  # re-apply (new) scorers to stored outputs; no agent calls
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from agentval.runner import apply_scorer_preset
from agentval.service import BUILTIN_DATASETS, SAMPLE_DIR

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
    if args.scorers:
        config = apply_scorer_preset(config, args.scorers)
    if args.trials:
        config["trials"] = args.trials
    color = sys.stdout.isatty() and not args.no_color
    dataset_arg = BUILTIN_DATASETS.get(args.dataset, args.dataset)
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
            Path(args.output).write_text(json.dumps({"name": cfg.name, "metrics": metrics,
                                                     "results": [{**o.__dict__, "test_case_name": names[o.test_case_id]}
                                                                 for o in outcomes]},
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

    print(json.dumps(asyncio.run(seed_sample(speed=args.speed, suite=not args.no_suite)), indent=2))
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


def _load_run(ref: str) -> dict[str, Any]:
    """A run id in the database or a JSON file written by ``agentval run -o``."""
    path = Path(ref)
    if path.exists():
        data = json.loads(path.read_text())
        if data.get("results") and "test_case_id" in data["results"][0]:  # --no-persist output
            data = {"name": data.get("name", path.stem), "results": [{**r, "testCaseId": r.get("test_case_id"), "testCaseName": r.get("test_case_name"),
                                                   "trial": r.get("trial", 0)}
                                                  for r in data["results"]], "metrics": data.get("metrics")}
        return data
    from agentval.db import session_scope
    from agentval.models import EvalRun
    from agentval.service import run_detail

    with session_scope() as s:
        run = s.get(EvalRun, ref)
        if run is None:
            raise SystemExit(f"Run not found: {ref} (pass a run id or a JSON file from `agentval run -o`)")
        return run_detail(s, run).model_dump(mode="json", by_alias=True)


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare two runs; with --fail-on-regression exit 1 when the gate fails (for CI)."""
    from agentval.regression import GatePolicy, analyze
    from agentval.reports import VERDICT_LABEL, compare_markdown

    if not (Path(args.run_a).exists() and Path(args.run_b).exists()):
        _setup_db(args.db)
    a, b = _load_run(args.run_a), _load_run(args.run_b)
    policy = GatePolicy(max_new_failures=args.max_new_failures, max_score_drop=args.max_score_drop,
                        require_significance=args.require_significance, alpha=args.alpha)
    report = analyze(a.get("results") or [], b.get("results") or [], policy).to_dict()
    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "md":
        print(compare_markdown(a.get("name", "A"), b.get("name", "B"), report))
    else:
        color = sys.stdout.isatty() and not args.no_color
        s, g = report["summary"], report["gate"]
        print(f"A: {a.get('name')}\nB: {b.get('name')}\n")
        for c in report["cases"]:
            mark = {"improved": "+", "regressed": "-", "unchanged": "=", "missing": "?"}[c["change"]]
            delta = "" if c["delta"] is None else f"{c['delta']:+.3f}"
            print(f"  {mark} {(c['testCaseName'] or c['testCaseId'])[:40]:<40} {c['statusA'] or '-':>7} -> "
                  f"{c['statusB'] or '-':<7} {delta:>7}")
        print(f"\nVerdict: {VERDICT_LABEL.get(s['verdict'], s['verdict'])}")
        print(f"  mean delta {s['meanDelta']:+.3f}  95% CI [{s['ci95'][0]:+.3f}, {s['ci95'][1]:+.3f}]  "
              f"p={s['pValue']:.3f}  pass->fail {s['newFailures']}  fail->pass {s['newPasses']}")
        label = "PASSED" if g["passed"] else "FAILED"
        if color:
            label = ("\033[32m" if g["passed"] else "\033[31m") + label + RESET
        print(f"Gate: {label}" + ("" if g["passed"] else " - " + "; ".join(g["reasons"])))
    if args.fail_on_regression and not report["gate"]["passed"]:
        return 1
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from agentval.reports import run_csv, run_markdown

    if not Path(args.run).exists():
        _setup_db(args.db)
    run = _load_run(args.run)
    text = {"md": run_markdown, "csv": run_csv, "json": lambda r: json.dumps(r, indent=2)}[args.format](run)
    if args.output:
        Path(args.output).write_text(text)
        print(f"Wrote {args.output}")
    else:
        print(text)
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """Re-score stored runs with current scorers (LLM-judge verdicts are reused, not re-requested)."""
    _setup_db(args.db)
    from agentval.service import rescore_run

    for run_id in args.runs:
        run = asyncio.run(rescore_run(run_id, args.scorers))
        m = run.metrics or {}
        print(f"{run.name}: pass rate {m.get('passRate', 0):.0%}, avg score {m.get('avgScore', 0):.3f}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Merge an export bundle (datasets, test cases, runs, results) into the database, keeping ids."""
    _setup_db(args.db)
    from agentval.db import session_scope
    from agentval.service import import_bundle

    total: dict[str, int] = {}
    for path in args.bundles:
        with session_scope() as s:
            counts = import_bundle(s, json.loads(Path(path).read_text()))
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
        print(f"{path}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentval", description="AgentVal - evaluate multi-step AI agents")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run an evaluation from the terminal")
    r.add_argument("--dataset", required=True, help="Dataset JSON path, dataset id in the DB, or a built-in: sample, rag, safety, ops")
    r.add_argument("--config", help="Config JSON path or built-in name (mock-baseline, mock-improved, litellm-openai)")
    r.add_argument("--name", help="Override run name")
    r.add_argument("--concurrency", type=int)
    r.add_argument("--trials", type=int, help="Repeat each case k times (enables pass@k / pass^k / consistency)")
    r.add_argument("--scorers", help="Scorer preset: default | full | deterministic (keeps the config's judge)")
    r.add_argument("--db", help="Database URL (default: $DATABASE_URL or sqlite:///./agentval.db)")
    r.add_argument("--no-persist", action="store_true", help="Run in-memory without writing to the database")
    r.add_argument("--output", "-o", help="Write full results (incl. traces) as JSON")
    r.add_argument("--quiet", "-q", action="store_true")
    r.add_argument("--no-color", action="store_true")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("seed", help="Load the sample dataset + benchmark suite and create baseline/improved mock runs")
    s.add_argument("--db")
    s.add_argument("--speed", type=float, default=1.0, help="Mock agent latency multiplier")
    s.add_argument("--no-suite", action="store_true", help="Only seed the customer-service sample dataset")
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
    c = sub.add_parser("compare", help="Compare two runs (ids or JSON files); CI gate with --fail-on-regression")
    c.add_argument("run_a", help="Baseline run id or JSON file")
    c.add_argument("run_b", help="Candidate run id or JSON file")
    c.add_argument("--fail-on-regression", action="store_true", help="Exit 1 if the regression gate fails")
    c.add_argument("--max-new-failures", type=int, default=0, help="Allowed pass->fail flips (default 0)")
    c.add_argument("--max-score-drop", type=float, default=0.02, help="Allowed mean score drop (default 0.02)")
    c.add_argument("--require-significance", action="store_true",
                   help="Only fail on a score drop if the paired bootstrap p-value < --alpha")
    c.add_argument("--alpha", type=float, default=0.05)
    c.add_argument("--format", choices=["text", "md", "json"], default="text")
    c.add_argument("--db")
    c.add_argument("--no-color", action="store_true")
    c.set_defaults(func=cmd_compare)

    rp = sub.add_parser("report", help="Render a run as Markdown, CSV or JSON")
    rp.add_argument("run", help="Run id or JSON file")
    rp.add_argument("--format", choices=["md", "csv", "json"], default="md")
    rp.add_argument("--output", "-o")
    rp.add_argument("--db")
    rp.set_defaults(func=cmd_report)

    rs = sub.add_parser("rescore", help="Re-apply scorers to stored runs without re-running the agent")
    rs.add_argument("runs", nargs="+", help="Run ids")
    rs.add_argument("--scorers", help="Switch to a scorer preset first: default | full | deterministic")
    rs.add_argument("--db")
    rs.set_defaults(func=cmd_rescore)

    i = sub.add_parser("import", help="Merge export bundles into the database (ids preserved, idempotent)")
    i.add_argument("bundles", nargs="+", help="JSON files written by export-demo")
    i.add_argument("--db")
    i.set_defaults(func=cmd_import)
    return p


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
