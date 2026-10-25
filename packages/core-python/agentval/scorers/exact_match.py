"""ExactMatchScorer: structural or exact string equality."""

from __future__ import annotations

import json
import re
from typing import Any

from agentval.scorers.base import Scorer, ScoreResult, ScoringContext, get_path, register_scorer


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip().lower()
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


@register_scorer("exact_match")
class ExactMatchScorer(Scorer):
    """Compare ``actual[field]`` with ``expected[expected_field]``.

    params:
      field:           dotted path into the actual output (default: whole output)
      expected_field:  dotted path into ``expected`` (default: same as ``field``, else ``output``)
      mode:            "exact" (default), "normalized" (case/whitespace-insensitive) or "json"
    """

    def score(self, ctx: ScoringContext) -> ScoreResult:
        field = self.params.get("field")
        expected_field = self.params.get("expected_field") or field or "output"
        mode = self.params.get("mode", "exact")
        if not ctx.expected:
            return self.skip("No expected output defined")
        try:
            expected = get_path(ctx.expected, expected_field)
        except KeyError:
            return self.skip(f"expected.{expected_field} not defined")
        try:
            actual = get_path(ctx.actual, field)
        except (KeyError, IndexError):
            return self.result(0.0, f"Actual output has no field '{field}'", expected=expected)

        if mode == "json":
            actual, expected = _maybe_json(actual), _maybe_json(expected)
        elif mode == "normalized":
            actual, expected = _normalize(actual), _normalize(expected)

        ok = actual == expected
        label = f"'{field}'" if field else "output"
        return self.result(
            1.0 if ok else 0.0,
            f"{label} matches expected" if ok else f"{label} differs: expected {expected!r}, got {actual!r}",
            expected=expected,
            actual=actual,
            mode=mode,
        )
