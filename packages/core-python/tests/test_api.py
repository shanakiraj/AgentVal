import time

import pytest
from fastapi.testclient import TestClient

from agentval.api.main import create_app

from conftest import fast_config


@pytest.fixture()
def client(db):
    with TestClient(create_app()) as c:
        yield c


def wait_done(client, run_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/evals/runs/{run_id}").json()
        if body["status"] in ("COMPLETED", "FAILED"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def make_dataset(client, sample_dataset):
    r = client.post("/api/v1/datasets", json=sample_dataset)
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_dataset_crud(client, sample_dataset):
    ds = make_dataset(client, sample_dataset)
    assert ds["testCaseCount"] == 5 and len(ds["testCases"]) == 5
    assert ds["testCases"][0]["name"] == "Order status lookup"
    listed = client.get("/api/v1/datasets").json()
    assert [d["id"] for d in listed] == [ds["id"]]

    one = client.post(f"/api/v1/datasets/{ds['id']}/testcases",
                      json={"name": "extra", "input": {"prompt": "hi"}, "expected": {"output": "hi"}})
    assert one.status_code == 201 and len(one.json()) == 1
    many = client.post(f"/api/v1/datasets/{ds['id']}/testcases",
                       json=[{"input": {"prompt": "a"}}, {"input": {"prompt": "b"}, "metadata": {"tag": "x"}}])
    assert len(many.json()) == 2 and many.json()[1]["metadata"] == {"tag": "x"}
    detail = client.get(f"/api/v1/datasets/{ds['id']}").json()
    assert detail["testCaseCount"] == 8 and detail["testCases"][-1]["input"] == {"prompt": "b"}

    tc_id = detail["testCases"][-1]["id"]
    assert client.delete(f"/api/v1/datasets/{ds['id']}/testcases/{tc_id}").status_code == 204
    assert client.delete(f"/api/v1/datasets/{ds['id']}").status_code == 204
    assert client.get(f"/api/v1/datasets/{ds['id']}").status_code == 404


def test_validation_errors(client):
    assert client.post("/api/v1/datasets", json={"name": ""}).status_code == 422
    assert client.post("/api/v1/datasets/nope/testcases", json={"input": {}}).status_code == 404
    assert client.post("/api/v1/evals/run", json={"datasetId": "nope"}).status_code == 404


def test_run_lifecycle_and_compare(client, sample_dataset):
    ds = make_dataset(client, sample_dataset)
    r = client.post("/api/v1/evals/run", json={"datasetId": ds["id"], "config": fast_config("mock-baseline")})
    assert r.status_code == 202, r.text
    assert r.json()["status"] in ("PENDING", "RUNNING", "COMPLETED") and r.json()["totalCases"] == 5
    a = wait_done(client, r.json()["id"])
    assert a["status"] == "COMPLETED" and a["completedCases"] == 5 and a["progress"] == 1.0
    m = a["metrics"]
    assert 0 < m["passRate"] < 1 and m["avgLatencyMs"] >= 0 and m["tokenCount"] > 0
    assert len(a["results"]) == 5
    res = a["results"][0]
    assert res["testCaseName"] == "Order status lookup" and res["trace"]["steps"]
    assert {"exact_match", "trajectory"} <= set(res["scores"])

    single = client.get(f"/api/v1/evals/runs/{a['id']}/results/{res['id']}").json()
    assert single["id"] == res["id"] and single["trace"]["traceId"]
    no_trace = client.get(f"/api/v1/evals/runs/{a['id']}?includeTraces=false").json()
    assert no_trace["results"][0]["trace"] is None

    b_id = client.post("/api/v1/evals/run", json={"datasetId": ds["id"], "name": "B",
                                                  "config": fast_config("mock-improved")}).json()["id"]
    b = wait_done(client, b_id)
    assert b["name"] == "B" and b["metrics"]["passRate"] == 1.0

    runs = client.get("/api/v1/evals/runs").json()
    assert {x["id"] for x in runs} == {a["id"], b_id}
    assert client.get(f"/api/v1/evals/runs?datasetId={ds['id']}").json()

    cmp = client.get(f"/api/v1/evals/compare?runA={a['id']}&runB={b_id}").json()
    pass_rate = next(x for x in cmp["metrics"] if x["metric"] == "passRate")
    assert pass_rate["better"] == "b" and pass_rate["delta"] > 0
    assert any(c["change"] == "improved" for c in cmp["cases"])
    assert len(cmp["cases"]) == 5
    reg = cmp["regression"]
    assert reg["summary"]["newPasses"] >= 1 and reg["gate"]["passed"] is True
    assert reg["summary"]["verdict"] in {"improvement", "possible_improvement"}
    back = client.get(f"/api/v1/evals/compare?runA={b_id}&runB={a['id']}&maxScoreDrop=0.5").json()
    assert back["regression"]["gate"]["passed"] is False  # pass->fail flips still fail the gate
    md = client.get(f"/api/v1/evals/compare/report?runA={a['id']}&runB={b_id}")
    assert md.status_code == 200 and "regression check: PASSED" in md.text

    rep = client.get(f"/api/v1/evals/runs/{a['id']}/report?format=md")
    assert rep.headers["content-type"].startswith("text/markdown") and "# AgentVal report" in rep.text
    csv_rep = client.get(f"/api/v1/evals/runs/{a['id']}/report?format=csv")
    assert csv_rep.text.splitlines()[0].startswith("test_case,trial,status") and len(csv_rep.text.splitlines()) == 6
    assert client.get(f"/api/v1/evals/runs/{a['id']}/report?format=xml").status_code == 422

    stream = client.get(f"/api/v1/evals/runs/{b_id}/stream")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in stream.text

    assert client.delete(f"/api/v1/evals/runs/{a['id']}").status_code == 204


def test_run_with_bad_config_fails_gracefully(client, sample_dataset):
    ds = make_dataset(client, sample_dataset)
    r = client.post("/api/v1/evals/run", json={"datasetId": ds["id"], "config": {"scorers": ["does_not_exist"]}})
    body = wait_done(client, r.json()["id"])
    assert body["status"] == "FAILED" and "does_not_exist" in body["error"]
    bad = client.post("/api/v1/evals/run", json={"datasetId": ds["id"], "config": {"concurrency": 0}})
    assert bad.status_code == 422


def test_scorers_endpoint(client):
    assert "llm_judge" in client.get("/api/v1/evals/scorers").json()
