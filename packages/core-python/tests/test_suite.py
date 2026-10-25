"""The bundled benchmark suite: datasets are valid and the mock agents show the intended behaviour."""

import json

import pytest

from agentval.agents.sandbox import search_kb
from agentval.runner import CaseInput, EvalConfig, apply_scorer_preset, run_evaluation
from agentval.service import BUILTIN_DATASETS, load_dataset_file

from conftest import fast_config

SUITE = ["rag", "safety", "ops"]


@pytest.mark.parametrize("key", SUITE)
def test_suite_datasets_are_valid_and_tagged(key):
    data = load_dataset_file(BUILTIN_DATASETS[key])
    assert len(data.test_cases) >= 5
    for tc in data.test_cases:
        assert tc.metadata and tc.metadata["difficulty"] in {"easy", "medium", "hard"}
        assert tc.metadata.get("tags") and tc.metadata.get("rationale")
        assert tc.input.get("system"), "suite cases carry their own policy prompt"
        assert tc.expected and tc.expected.get("schema")


def test_kb_retrieval_finds_the_right_article():
    data = load_dataset_file(BUILTIN_DATASETS["rag"])
    by_name = {tc.name: tc for tc in data.test_cases}
    kb = by_name["Return window"].input["context"]["kb"]
    assert search_kb("How many days do I have to return a jacket?", kb)[0]["id"] == "KB-101"
    assert search_kb("loyalty points per dollar", kb) == []
    assert {d["id"] for d in search_kb("will you price match", kb)} == {"KB-104", "KB-105"}


async def _run(key, variant, trials=1):
    data = load_dataset_file(BUILTIN_DATASETS[key])
    cases = [CaseInput(id=tc.name, input=tc.input, expected=tc.expected, metadata=tc.metadata, name=tc.name)
             for tc in data.test_cases]
    cfg = apply_scorer_preset(fast_config(f"mock-{variant}"), "full")
    cfg["agent"]["flaky"] = False
    cfg["trials"] = trials
    return await run_evaluation(cases, EvalConfig.model_validate(cfg), seed=1)


@pytest.mark.parametrize("key", SUITE)
async def test_improved_mock_beats_baseline(key):
    _, base = await _run(key, "baseline")
    _, imp = await _run(key, "improved")
    assert imp["passRate"] > base["passRate"] and imp["avgScore"] > base["avgScore"]


async def test_baseline_falls_for_known_attacks():
    outcomes, _ = await _run("safety", "baseline")
    by = {o.test_case_id: o for o in outcomes}
    assert by["Injection in order note"].scores["safety"]["score"] == 0.0
    assert by["System prompt extraction"].scores["safety"]["details"]["leaked"]
    rag, _ = await _run("rag", "baseline")
    assert {o.test_case_id: o for o in rag}["Unanswerable: loyalty points"].scores["groundedness"]["score"] == 0.0


async def test_trials_produce_pass_at_k_metrics():
    outcomes, metrics = await _run("ops", "baseline", trials=3)
    assert len(outcomes) == 15 and metrics["trials"] == 3 and metrics["cases"] == 5
    assert 0 <= metrics["passHatK"] <= metrics["passAtK"] <= 1
    assert {o.trial for o in outcomes} == {0, 1, 2}
    assert set(metrics["difficultyBreakdown"]) <= {"easy", "medium", "hard"}
    assert "multi-intent" in metrics["tagBreakdown"]
    lo, hi = metrics["passRateCi"]
    assert lo <= metrics["passRate"] <= hi


def test_scorer_preset_keeps_judge():
    cfg = apply_scorer_preset(json.loads(json.dumps(fast_config("mock-baseline"))), "full")
    types = [s["type"] for s in cfg["scorers"]]
    assert types[-1] == "llm_judge" and {"contains", "groundedness", "safety"} <= set(types)
    with pytest.raises(ValueError):
        apply_scorer_preset(cfg, "nope")
