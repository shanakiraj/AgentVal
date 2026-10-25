import pytest

from agentval.scorers import (
    ExactMatchScorer,
    LLMJudgeScorer,
    SchemaMatchScorer,
    Scorer,
    ScoringContext,
    TrajectoryScorer,
    available_scorers,
    build_scorer,
    register_scorer,
)
from agentval.scorers.llm_judge import parse_judge_response

SCHEMA = {"type": "object", "required": ["reply"], "properties": {"reply": {"type": "string"}}}


def ctx(actual, expected=None, steps=None, input=None):
    return ScoringContext(input=input or {}, expected=expected, actual=actual, trace={"steps": steps or []})


def tool(name, args=None, status="ok"):
    return {"type": "tool_call", "name": name, "input": args or {}, "status": status}


def llm():
    return {"type": "llm", "name": "plan"}


# ---------------------------------------------------------------- registry
def test_registry_has_builtins():
    assert {"exact_match", "schema_match", "llm_judge", "trajectory"} <= set(available_scorers())


def test_build_scorer_from_spec():
    s = build_scorer({"type": "exact_match", "weight": 2, "params": {"field": "a"}})
    assert isinstance(s, ExactMatchScorer) and s.weight == 2 and s.params["field"] == "a"


def test_unknown_scorer():
    with pytest.raises(KeyError):
        build_scorer("nope")


def test_custom_scorer_registration():
    @register_scorer("always_half")
    class Half(Scorer):
        def score(self, ctx):
            return self.result(0.5, "half")

    assert build_scorer("always_half").score(ctx("x")).score == 0.5


def test_plugin_dotted_path():
    s = build_scorer("agentval.scorers.exact_match:ExactMatchScorer")
    assert isinstance(s, ExactMatchScorer)


# ---------------------------------------------------------------- exact match
def test_exact_match_string():
    s = ExactMatchScorer()
    assert s.score(ctx("Paris", {"output": "Paris"})).score == 1.0
    assert s.score(ctx("paris", {"output": "Paris"})).score == 0.0


def test_exact_match_normalized():
    r = ExactMatchScorer(mode="normalized").score(ctx("  PARIS \n", {"output": "paris"}))
    assert r.passed


def test_exact_match_structural_and_field():
    s = ExactMatchScorer(field="resolution")
    assert s.score(ctx({"resolution": "resolved", "x": 1}, {"resolution": "resolved"})).score == 1.0
    assert s.score(ctx({"resolution": "escalated"}, {"resolution": "resolved"})).score == 0.0
    assert ExactMatchScorer().score(ctx({"a": [1, 2]}, {"output": {"a": [1, 2]}})).passed


def test_exact_match_json_mode():
    assert ExactMatchScorer(mode="json").score(ctx('{"a": 1}', {"output": {"a": 1}})).passed


def test_exact_match_skips_without_expected():
    assert ExactMatchScorer().score(ctx("x", None)).skipped
    assert ExactMatchScorer(field="foo").score(ctx({"foo": 1}, {"bar": 1})).skipped


def test_exact_match_missing_actual_field():
    assert ExactMatchScorer(field="foo").score(ctx({}, {"foo": 1})).score == 0.0


# ---------------------------------------------------------------- schema match
def test_schema_match_from_expected():
    s = SchemaMatchScorer()
    assert s.score(ctx({"reply": "hi"}, {"schema": SCHEMA})).score == 1.0
    bad = s.score(ctx({"reply": 3}, {"schema": SCHEMA}))
    assert bad.score == 0.0 and "violation" in bad.rationale


def test_schema_match_json_string_and_invalid_json():
    s = SchemaMatchScorer(schema=SCHEMA)
    assert s.score(ctx('{"reply": "ok"}')).passed
    assert not s.score(ctx("not json")).passed


def test_schema_match_pydantic_model():
    from pydantic import BaseModel

    class Out(BaseModel):
        reply: str
        n: int

    s = SchemaMatchScorer(model=Out)
    assert s.score(ctx({"reply": "a", "n": 1})).passed
    assert not s.score(ctx({"reply": "a"})).passed


def test_schema_match_skip():
    assert SchemaMatchScorer().score(ctx({})).skipped


# ---------------------------------------------------------------- llm judge
async def test_llm_judge_mock_keywords():
    s = LLMJudgeScorer(model="mock")
    exp = {"reply_contains": ["refund", "3-5 business days"], "reply_must_not_contain": ["calm down"]}
    good = await s.ascore(ctx({"reply": "Refund issued, 3-5 business days."}, exp))
    assert good.score == 1.0 and good.passed
    half = await s.ascore(ctx({"reply": "Refund issued."}, exp))
    assert half.score == 0.5 and not half.passed
    rude = await s.ascore(ctx({"reply": "Calm down. Refund issued, 3-5 business days."}, exp))
    assert rude.score == 0.5 and "violations" in rude.rationale


async def test_llm_judge_with_injected_completion():
    calls = {}

    async def fake_completion(**kwargs):
        calls.update(kwargs)
        return {"choices": [{"message": {"content": '```json\n{"score": 0.85, "rationale": "Good"}\n```'}}]}

    s = LLMJudgeScorer(model="gpt-4o-mini", completion_fn=fake_completion, rubric="Be nice")
    r = await s.ascore(ctx("answer", {"output": "answer"}, input={"prompt": "q"}))
    assert r.score == 0.85 and r.rationale == "Good" and r.passed
    assert calls["model"] == "gpt-4o-mini" and "Be nice" in calls["messages"][0]["content"]


def test_parse_judge_response_variants():
    assert parse_judge_response('{"score": 1.4, "rationale": "x"}')[0] == 1.0
    assert parse_judge_response("Score: 0.3 because...")[0] == 0.3
    with pytest.raises(ValueError):
        parse_judge_response("no idea")


# ---------------------------------------------------------------- trajectory
EXP = {"tool_calls": [{"name": "lookup_order", "args": {"order_id": "A1"}}, {"name": "issue_refund"}], "max_steps": 3}


def test_trajectory_perfect():
    r = TrajectoryScorer().score(ctx({}, EXP, [llm(), tool("lookup_order", {"order_id": "A1"}), tool("issue_refund")]))
    assert r.score == pytest.approx(1.0)
    assert r.details["invalid_invocations"] == 0


def test_trajectory_invalid_and_missing():
    steps = [llm(), tool("check_policy", status="error"), tool("issue_refund")]
    r = TrajectoryScorer().score(ctx({}, EXP, steps))
    c = r.details["components"]
    assert c["recall"] == 0.5 and c["precision"] == 0.5 and c["validity"] == 0.5 and c["order"] == 0.0
    assert r.score < 0.6 and "invalid" in r.rationale.lower()


def test_trajectory_unknown_tool_against_available():
    steps = [tool("hack_db")]
    r = TrajectoryScorer().score(ctx({}, {"tool_calls": []}, steps, input={"tools": ["lookup_order"]}))
    assert r.details["invalid_invocations"] == 1


def test_trajectory_wrong_args_and_order():
    steps = [tool("issue_refund"), tool("lookup_order", {"order_id": "A1"})]
    r = TrajectoryScorer().score(ctx({}, EXP, steps))
    assert r.details["components"]["order"] == 0.0
    wrong = TrajectoryScorer().score(ctx({}, EXP, [tool("lookup_order", {"order_id": "ZZ"}), tool("issue_refund")]))
    assert wrong.details["components"]["recall"] == 0.5


def test_trajectory_efficiency_budget():
    steps = [llm(), llm(), tool("lookup_order", {"order_id": "A1"}), tool("issue_refund"), llm(), llm()]
    r = TrajectoryScorer().score(ctx({}, EXP, steps))
    assert r.details["components"]["efficiency"] == 0.5


def test_trajectory_skip():
    assert TrajectoryScorer().score(ctx({}, {"output": 1})).skipped
