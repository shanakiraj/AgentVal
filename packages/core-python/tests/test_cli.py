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
