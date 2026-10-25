import json

from agentval.cli import main

from conftest import SAMPLE


def test_cli_run_persists_and_exports(tmp_path, monkeypatch, capsys):
    db = f"sqlite:///{tmp_path / 'cli.db'}"
    cfg = json.loads((SAMPLE / "configs" / "mock-baseline.json").read_text())
    cfg["agent"]["speed"] = 0
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    out = tmp_path / "out.json"

    rc = main(["run", "--dataset", str(SAMPLE / "customer_service.json"), "--config", str(cfg_path),
               "--db", db, "--output", str(out), "--no-color"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "pass rate" in text and "Customer Service Agent Evaluation" in text
    data = json.loads(out.read_text())
    assert data["status"] == "COMPLETED" and data["metrics"]["total"] == 5

    # second run reuses the dataset by name; then run by dataset id
    rc = main(["run", "--dataset", data["datasetId"], "--config", str(cfg_path), "--db", db, "-q"])
    assert rc == 0

    demo = tmp_path / "demo.json"
    assert main(["export-demo", "--db", db, "--output", str(demo)]) == 0
    exported = json.loads(demo.read_text())
    assert len(exported["datasets"]) == 1 and len(exported["runs"]) == 2


def test_cli_no_persist(tmp_path, capsys):
    cfg = json.loads((SAMPLE / "configs" / "mock-improved.json").read_text())
    cfg["agent"]["speed"] = 0
    cfg["retry_base_delay"] = 0
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg))
    assert main(["run", "--dataset", "sample", "--config", str(p), "--no-persist", "--no-color"]) == 0
    assert "100%" in capsys.readouterr().out


def _fast_cfg(tmp_path, name):
    cfg = json.loads((SAMPLE / "configs" / f"{name}.json").read_text())
    cfg["agent"].update(speed=0, flaky=False)
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(cfg))
    return str(p)


def test_cli_compare_gate_exit_codes(tmp_path, capsys):
    base, imp = tmp_path / "base.json", tmp_path / "imp.json"
    for cfg, out in (("mock-baseline", base), ("mock-improved", imp)):
        assert main(["run", "--dataset", "ops", "--config", _fast_cfg(tmp_path, cfg), "--scorers", "full",
                     "--no-persist", "-q", "-o", str(out)]) in (0, 1)
    capsys.readouterr()
    # improved -> baseline is a regression: gate fails with exit 1
    assert main(["compare", str(imp), str(base), "--fail-on-regression", "--no-color"]) == 1
    assert "Gate: FAILED" in capsys.readouterr().out
    # baseline -> improved passes; markdown output is PR-comment ready
    assert main(["compare", str(base), str(imp), "--fail-on-regression", "--format", "md"]) == 0
    md = capsys.readouterr().out
    assert "regression check: PASSED" in md and "Two orders, two intents" in md
    # without the flag a regression is reported but does not fail
    assert main(["compare", str(imp), str(base), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["gate"]["passed"] is False


def test_cli_report_and_import_roundtrip(tmp_path, capsys):
    db = f"sqlite:///{tmp_path / 'a.db'}"
    out = tmp_path / "run.json"
    assert main(["run", "--dataset", "safety", "--config", _fast_cfg(tmp_path, "mock-improved"), "--scorers", "full",
                 "--trials", "2", "--db", db, "-q", "-o", str(out)]) == 0
    run = json.loads(out.read_text())
    assert run["metrics"]["trials"] == 2 and len(run["results"]) == 12
    capsys.readouterr()
    assert main(["report", run["id"], "--db", db, "--format", "md"]) == 0
    md = capsys.readouterr().out
    assert "# AgentVal report" in md and "pass@k" in md and "By tag" in md
    assert main(["report", str(out), "--format", "csv", "-o", str(tmp_path / "r.csv")]) == 0
    assert (tmp_path / "r.csv").read_text().count("\n") == 13

    bundle = tmp_path / "bundle.json"
    assert main(["export-demo", "--db", db, "-o", str(bundle)]) == 0
    db2 = f"sqlite:///{tmp_path / 'b.db'}"
    assert main(["import", str(bundle), "--db", db2]) == 0
    assert main(["import", str(bundle), "--db", db2]) == 0  # idempotent
    assert "0 runs" in capsys.readouterr().out
    again = tmp_path / "again.json"
    assert main(["export-demo", "--db", db2, "-o", str(again)]) == 0
    a, b = json.loads(bundle.read_text()), json.loads(again.read_text())
    assert [r["id"] for r in a["runs"]] == [r["id"] for r in b["runs"]]
    assert a["runs"][0]["results"] == b["runs"][0]["results"]


def test_cli_rescore_adds_scorers_without_rerunning(tmp_path, capsys):
    db = f"sqlite:///{tmp_path / 'r.db'}"
    out = tmp_path / "run.json"
    assert main(["run", "--dataset", "safety", "--config", _fast_cfg(tmp_path, "mock-baseline"), "--db", db, "-q",
                 "-o", str(out)]) in (0, 1)
    before = json.loads(out.read_text())
    assert "safety" not in before["results"][0]["scores"]
    assert main(["rescore", before["id"], "--scorers", "full", "--db", db]) == 0
    capsys.readouterr()
    assert main(["report", before["id"], "--db", db, "--format", "json"]) == 0
    after = json.loads(capsys.readouterr().out)
    assert "safety" in after["results"][0]["scores"]
    assert [r["actual"] for r in after["results"]] == [r["actual"] for r in before["results"]]  # outputs untouched
    assert after["metrics"]["scorerAverages"]["safety"] < 1  # baseline falls for the attacks
