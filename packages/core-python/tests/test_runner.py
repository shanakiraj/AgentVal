import asyncio
import random

import pytest

from agentval.agents.base import Agent
from agentval.runner import CaseInput, EvalConfig, aggregate, backoff_delay, run_evaluation
from agentval.scorers import ScoreResult

from conftest import fast_config


def cases_from(ds):
    return [CaseInput(id=str(i), input=c["input"], expected=c.get("expected"), name=c["name"])
            for i, c in enumerate(ds["testCases"])]


async def test_mock_improved_all_pass(sample_dataset):
    cfg = EvalConfig.model_validate(fast_config("mock-improved"))
    outcomes, m = await run_evaluation(cases_from(sample_dataset), cfg, seed=1)
    assert m["total"] == 5 and m["passRate"] == 1.0
    assert m["totalRetries"] >= 1  # flaky=True simulates a transient 429
    assert all(o.trace["steps"][0]["type"] == "input" for o in outcomes)
    assert m["tokenCount"] > 0 and m["totalCostUsd"] > 0
    assert set(m["scorerAverages"]) == {"exact_match", "schema_match", "llm_judge", "trajectory"}


async def test_mock_baseline_mixed(sample_dataset):
    cfg = EvalConfig.model_validate(fast_config("mock-baseline"))
    outcomes, m = await run_evaluation(cases_from(sample_dataset), cfg)
    statuses = {o.status for o in outcomes}
    assert {"PASS", "PARTIAL", "FAIL"} <= statuses
    assert m["passRate"] < 1.0
    addr = next(o for o in outcomes if o.test_case_id == "3")
    assert addr.status == "FAIL" and addr.scores["exact_match"]["score"] == 0.0


class SlowAgent(Agent):
    def __init__(self):
        super().__init__()
        self.active = 0
        self.peak = 0

    async def run(self, input, recorder):
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        recorder.add_step("output", "final", output=input["x"])
        return input["x"]


async def test_semaphore_bounds_concurrency():
    agent = SlowAgent()
    cases = [CaseInput(id=str(i), input={"x": i}, expected={"output": i}) for i in range(12)]
    cfg = EvalConfig(concurrency=3, scorers=["exact_match"])
    outcomes, m = await run_evaluation(cases, cfg, agent=agent)
    assert agent.peak == 3
    assert m["passRate"] == 1.0 and len(outcomes) == 12


class FlakyAgent(Agent):
    def __init__(self, fail_times):
        super().__init__()
        self.fail_times = fail_times
        self.calls = 0

    async def run(self, input, recorder):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("boom")
        return "ok"


async def test_retries_then_success():
    agent = FlakyAgent(2)
    cfg = EvalConfig(max_retries=2, retry_base_delay=0.001, scorers=["exact_match"])
    [o], m = await run_evaluation([CaseInput(id="1", input={}, expected={"output": "ok"})], cfg, agent=agent)
    assert o.status == "PASS" and o.attempts == 3 and len(o.trace["retries"]) == 2
    assert m["totalRetries"] == 2


async def test_retries_exhausted_marks_error():
    agent = FlakyAgent(10)
    cfg = EvalConfig(max_retries=1, retry_base_delay=0.001, scorers=["exact_match"])
    [o], m = await run_evaluation([CaseInput(id="1", input={})], cfg, agent=agent)
    assert o.status == "ERROR" and o.attempts == 2 and "ConnectionError" in o.error
    assert o.trace["steps"][-1]["type"] == "error"
    assert m["errored"] == 1


class HangingAgent(Agent):
    async def run(self, input, recorder):
        await asyncio.sleep(10)


async def test_timeout_is_error():
    cfg = EvalConfig(max_retries=0, timeout_s=0.05, scorers=["exact_match"])
    [o], _ = await run_evaluation([CaseInput(id="1", input={})], cfg, agent=HangingAgent())
    assert o.status == "ERROR" and "Timeout" in o.error


def test_backoff_is_exponential_and_capped():
    rng = random.Random(0)
    d = [backoff_delay(i, 0.5, 4.0, rng) for i in range(6)]
    assert 0.5 <= d[0] <= 0.625 and 1.0 <= d[1] <= 1.25 and 2.0 <= d[2] <= 2.5
    assert all(x <= 5.0 for x in d[3:])


def test_aggregate_weights_and_skips():
    rs = [ScoreResult(name="a", score=1.0, passed=True, weight=1),
          ScoreResult(name="b", score=0.0, passed=False, weight=3),
          ScoreResult(name="c", score=0.0, passed=True, skipped=True, weight=100)]
    assert aggregate(rs) == pytest.approx(0.25)
    assert aggregate([]) == 0.0


async def test_on_result_callback_progress():
    seen = []
    cases = [CaseInput(id=str(i), input={"x": i}) for i in range(4)]
    await run_evaluation(cases, EvalConfig(scorers=[]), agent=SlowAgent(),
                         on_result=lambda o, done, total: seen.append((done, total)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]
