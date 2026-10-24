"""LiteLLM agent + judge paths with a fake completion function (no network, no keys)."""

import json
from types import SimpleNamespace as NS

import litellm
import pytest

from agentval.agents.base import TraceRecorder
from agentval.agents.litellm_agent import LiteLLMToolAgent, parse_final
from agentval.scorers import LLMJudgeScorer, ScoringContext

from conftest import SAMPLE


def _resp(content=None, tool_calls=None):
    msg = NS(content=content, tool_calls=tool_calls, reasoning_content="thinking...")
    usage = NS(prompt_tokens=100, completion_tokens=20, cost=0)
    return NS(choices=[NS(message=msg, finish_reason="stop")], usage=usage)


def _call(name, args, id_="c1"):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


@pytest.fixture()
def refund_case():
    ds = json.loads((SAMPLE / "customer_service.json").read_text())
    return next(c for c in ds["testCases"] if c["name"] == "Refund for damaged item")


async def test_tool_loop_uses_sandbox_and_parses_json(monkeypatch, refund_case):
    script = [
        _resp(tool_calls=[_call("lookup_order", {"order_id": "B2002"})]),
        _resp(tool_calls=[_call("issue_refund", {"order_id": "B2002", "reason": "damaged"}, "c2")]),
        _resp(content='```json\n{"reply": "Refunded $49.99", "resolution": "resolved", "actions": ["issue_refund"]}\n```'),
    ]
    seen = []

    async def fake(**kw):
        seen.append(kw)
        return script.pop(0)

    monkeypatch.setattr(litellm, "acompletion", fake)
    rec = TraceRecorder()
    out = await LiteLLMToolAgent(model="openrouter/some/model:free").run(refund_case["input"], rec)
    assert out["resolution"] == "resolved"
    tools = [s for s in rec.steps if s["type"] == "tool_call"]
    assert [t["name"] for t in tools] == ["lookup_order", "issue_refund"]
    assert tools[0]["output"]["total"] == 49.99 and tools[1]["output"]["amount"] == 49.99
    # full OpenAI-style schemas are sent for sandbox tools
    names = {t["function"]["name"] for t in seen[0]["tools"]}
    assert "issue_refund" in names and seen[0]["tools"][0]["function"]["parameters"]["properties"]
    # free models cost $0; trace keeps reasoning but never credentials
    assert rec.cost_usd == 0 and rec.prompt_tokens == 300
    dumped = json.dumps(rec.to_dict())
    assert "Authorization" not in dumped and "api_key" not in dumped
    assert rec.steps[1]["attributes"]["reasoning"] == "thinking..."


async def test_rate_limit_retry(monkeypatch, refund_case):
    calls = {"n": 0}

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise litellm.RateLimitError("429", llm_provider="openrouter", model="x")
        return _resp(content='{"reply": "hi", "resolution": "resolved", "actions": []}')

    monkeypatch.setattr(litellm, "acompletion", flaky)
    rec = TraceRecorder()
    await LiteLLMToolAgent(model="m", retry_base_delay=0.001).run(refund_case["input"], rec)
    assert calls["n"] == 2 and rec.steps[1]["attributes"]["rate_limit_retries"] == 1


async def test_unknown_tool_is_invalid(monkeypatch, refund_case):
    script = [_resp(tool_calls=[_call("hack_db", {})]), _resp(content="plain text answer")]

    async def fake(**kw):
        return script.pop(0)

    monkeypatch.setattr(litellm, "acompletion", fake)
    rec = TraceRecorder()
    out = await LiteLLMToolAgent(model="m").run(refund_case["input"], rec)
    assert out == {"reply": "plain text answer"}
    assert [s["status"] for s in rec.steps if s["type"] == "tool_call"] == ["error"]


def test_parse_final_variants():
    assert parse_final('Here you go: {"reply": "a", "resolution": "resolved"} thanks')["resolution"] == "resolved"
    assert parse_final("no json") == {"reply": "no json"}


async def test_judge_outage_is_skipped_not_zero():
    async def broken(**kw):
        raise RuntimeError("provider down")

    s = LLMJudgeScorer(model="openrouter/x:free", completion_fn=broken, retries=1, retry_base_delay=0.001)
    r = await s.ascore(ScoringContext(actual={"reply": "x"}))
    assert r.skipped and "Judge unavailable" in r.rationale
