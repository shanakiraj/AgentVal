"""TrajectoryScorer: tool-calling efficiency and correctness of the agent's trajectory."""

from __future__ import annotations

from typing import Any

from agentval.scorers.base import Scorer, ScoreResult, ScoringContext, register_scorer


def _args_match(expected: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    if not expected:
        return True
    actual = actual or {}
    return all(actual.get(k) == v for k, v in expected.items())


@register_scorer("trajectory")
class TrajectoryScorer(Scorer):
    """Scores the tool-call trajectory found in ``trace.steps`` (type == "tool_call").

    Expected (from test case ``expected``):
      tool_calls: [{"name": str, "args": {...subset...}, "expect_error": bool}, ...]   ordered golden calls
                  (``expect_error`` marks calls that legitimately fail, e.g. looking up an unknown order)
      max_steps:  int   step budget (LLM + tool steps)

    Components (weighted average):
      recall      fraction of expected tool calls present (name + arg subset)
      precision   fraction of actual tool calls that were expected
      order       1 if expected calls appear in order, else 0
      validity    1 - invalid_invocations / total tool calls (unknown tool or errored call)
      efficiency  min(1, max_steps / actual_steps)
    """

    DEFAULT_WEIGHTS = {"recall": 0.35, "precision": 0.2, "order": 0.15, "validity": 0.15, "efficiency": 0.15}

    def score(self, ctx: ScoringContext) -> ScoreResult:
        expected = ctx.expected or {}
        exp_calls: list[dict[str, Any]] | None = expected.get("tool_calls")
        max_steps = expected.get("max_steps") or self.params.get("max_steps")
        if exp_calls is None and max_steps is None:
            return self.skip("No expected tool_calls or max_steps")

        steps = ctx.trace.get("steps", []) if isinstance(ctx.trace, dict) else []
        tool_steps = [s for s in steps if s.get("type") == "tool_call"]
        work_steps = [s for s in steps if s.get("type") in {"llm", "tool_call"}]
        available = set(self.params.get("available_tools") or ctx.input.get("tools") or [])
        available = {t["name"] if isinstance(t, dict) else t for t in available} if available else set()

        actual_calls = [
            {"name": s.get("name"), "args": (s.get("input") or {}), "status": s.get("status", "ok")}
            for s in tool_steps
        ]
        expected_errors = {(ec.get("name")) for ec in (exp_calls or []) if ec.get("expect_error")}
        invalid = [
            c for c in actual_calls
            if (c["status"] == "error" and c["name"] not in expected_errors)
            or (available and c["name"] not in available)
        ]

        comps: dict[str, float] = {}
        exp_calls = exp_calls or []
        if exp_calls or "tool_calls" in expected:
            matched_actual: set[int] = set()
            hits: list[int] = []
            for ec in exp_calls:
                for i, ac in enumerate(actual_calls):
                    if i in matched_actual:
                        continue
                    ok_status = ac["status"] != "error" or ec.get("expect_error")
                    if ac["name"] == ec.get("name") and ok_status and _args_match(ec.get("args"), ac["args"]):
                        matched_actual.add(i)
                        hits.append(i)
                        break
            comps["recall"] = len(hits) / len(exp_calls) if exp_calls else 1.0
            comps["precision"] = (len(matched_actual) / len(actual_calls)) if actual_calls else (1.0 if not exp_calls else 0.0)
            comps["order"] = 1.0 if hits == sorted(hits) and len(hits) == len(exp_calls) else (0.0 if exp_calls else 1.0)
        comps["validity"] = 1.0 - (len(invalid) / len(actual_calls)) if actual_calls else 1.0
        if max_steps:
            comps["efficiency"] = min(1.0, max_steps / max(1, len(work_steps)))

        weights = {**self.DEFAULT_WEIGHTS, **(self.params.get("weights") or {})}
        total_w = sum(weights[k] for k in comps)
        value = sum(comps[k] * weights[k] for k in comps) / total_w if total_w else 0.0

        notes = []
        if comps.get("recall", 1.0) < 1:
            notes.append("missing expected tool calls")
        if comps.get("precision", 1.0) < 1:
            notes.append("unexpected tool calls")
        if comps.get("order", 1.0) < 1 and exp_calls:
            notes.append("tool calls out of order")
        if invalid:
            notes.append(f"{len(invalid)} invalid tool invocation(s)")
        if comps.get("efficiency", 1.0) < 1:
            notes.append(f"{len(work_steps)} steps exceeds budget of {max_steps}")
        rationale = "Efficient, correct trajectory" if not notes else "; ".join(notes).capitalize()
        return self.result(
            value,
            rationale,
            components=comps,
            tool_calls=[c["name"] for c in actual_calls],
            invalid_invocations=len(invalid),
            steps=len(work_steps),
        )
