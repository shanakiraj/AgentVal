"""LLMJudgeScorer: rubric-based model evaluation returning a 0.0-1.0 score and rationale."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any, Awaitable, Callable

from agentval.scorers.base import Scorer, ScoreResult, ScoringContext, register_scorer

DEFAULT_RUBRIC = (
    "Score how well the agent's final answer resolves the user's request: correctness, "
    "helpfulness, policy compliance and tone. 1.0 = perfect, 0.0 = useless or harmful."
)

JUDGE_PROMPT = """You are an impartial evaluator of AI agent outputs.

Rubric:
{rubric}

User input:
{input}

Reference / expected (may be partial):
{expected}

Agent final output:
{actual}

Respond ONLY with a JSON object: {{"score": <float between 0 and 1>, "rationale": "<one or two sentences>"}}"""

CompletionFn = Callable[..., Awaitable[Any]]


def _dump(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=2, default=str)


def parse_judge_response(text: str) -> tuple[float, str]:
    """Extract ``score`` and ``rationale`` from a judge model reply (robust to code fences)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return max(0.0, min(1.0, float(data["score"]))), str(data.get("rationale", ""))
        except (ValueError, KeyError, TypeError):
            pass
    num = re.search(r"(?<![\d.])(0(?:\.\d+)?|1(?:\.0+)?)(?![\d.])", text)
    if num:
        return float(num.group(1)), text.strip()[:500]
    raise ValueError(f"Could not parse judge response: {text[:200]!r}")


def _text_of(actual: Any) -> str:
    if isinstance(actual, dict):
        for key in ("reply", "output", "answer", "response", "text"):
            if isinstance(actual.get(key), str):
                return actual[key]
    return _dump(actual)


@register_scorer("llm_judge")
class LLMJudgeScorer(Scorer):
    """params:
      model:          LiteLLM model id (e.g. "gpt-4o-mini", "anthropic/claude-3-5-sonnet-20240620",
                      "ollama/llama3"). Use "mock" for an offline deterministic heuristic judge.
      rubric:         grading rubric (default: generic helpfulness rubric)
      temperature:    default 0
      completion_fn:  optional injectable async completion fn (testing / custom gateways)
    """

    def __init__(self, completion_fn: CompletionFn | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("threshold", 0.7)
        super().__init__(**kwargs)
        self.completion_fn = completion_fn

    def _mock_judge(self, ctx: ScoringContext) -> ScoreResult:
        """Offline heuristic: keyword coverage of expected.reply_contains + penalties for must_not_contain."""
        text = _text_of(ctx.actual).lower()
        expected = ctx.expected or {}
        must = [k.lower() for k in expected.get("reply_contains", [])]
        must_not = [k.lower() for k in expected.get("reply_must_not_contain", [])]
        if not must and not must_not:
            ref = _text_of(expected.get("output", "")).lower()
            ref_words, words = set(re.findall(r"\w+", ref)), set(re.findall(r"\w+", text))
            score = len(ref_words & words) / len(ref_words) if ref_words else (1.0 if text else 0.0)
            return self.result(score, f"[mock judge] {score:.0%} token overlap with reference", judge="mock")
        hits = [k for k in must if k in text]
        violations = [k for k in must_not if k in text]
        score = (len(hits) / len(must)) if must else 1.0
        score = max(0.0, score - 0.5 * len(violations))
        missing = sorted(set(must) - set(hits))
        parts = [f"covers {len(hits)}/{len(must)} required points"]
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if violations:
            parts.append("policy violations: " + ", ".join(violations))
        return self.result(score, "[mock judge] " + "; ".join(parts), judge="mock", missing=missing, violations=violations)

    async def score(self, ctx: ScoringContext) -> ScoreResult:  # type: ignore[override]
        model = self.params.get("model", "mock")
        if model == "mock" and self.completion_fn is None:
            return self._mock_judge(ctx)

        prompt = JUDGE_PROMPT.format(
            rubric=self.params.get("rubric", DEFAULT_RUBRIC),
            input=_dump(ctx.input),
            expected=_dump(ctx.expected or {}),
            actual=_dump(ctx.actual),
        )
        completion = self.completion_fn
        if completion is None:
            import litellm  # lazy: heavy import, only needed for real judges

            litellm.suppress_debug_info = True
            completion = litellm.acompletion
        retries = int(self.params.get("retries", 3))
        base_delay = float(self.params.get("retry_base_delay", 4.0))
        last_error = ""
        for attempt in range(retries + 1):
            try:
                response = await completion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.params.get("temperature", 0),
                    max_tokens=self.params.get("max_tokens", 1024),
                )
                text = (response["choices"][0]["message"]["content"] if isinstance(response, dict)
                        else response.choices[0].message.content)
                score, rationale = parse_judge_response(text or "")
                return self.result(score, rationale, judge=model, attempts=attempt + 1)
            except Exception as exc:  # rate limit, provider error or unparseable verdict
                last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                logging.getLogger("agentval.scorers").warning("judge %s attempt %d failed: %s", model, attempt + 1,
                                                              type(exc).__name__)
                if attempt < retries:
                    await asyncio.sleep(base_delay * (2**attempt) * (1 + random.random() * 0.25))
        # A judge outage must not silently score the agent 0: exclude this scorer for the case.
        res = self.skip(f"Judge unavailable after {retries + 1} attempts ({last_error})")
        res.details = {"judge": model, "error": last_error}
        return res
