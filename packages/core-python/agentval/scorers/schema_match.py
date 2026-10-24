"""SchemaMatchScorer: validate output against a JSON schema or Pydantic model."""

from __future__ import annotations

import importlib
import json
from typing import Any

import jsonschema
from pydantic import BaseModel

from agentval.scorers.base import Scorer, ScoreResult, ScoringContext, get_path, register_scorer


@register_scorer("schema_match")
class SchemaMatchScorer(Scorer):
    """params:
      schema:  inline JSON schema (else ``expected.schema`` is used)
      model:   "pkg.module:PydanticModel" or a BaseModel subclass (takes precedence)
      field:   dotted path into the actual output to validate (default whole output)
    """

    def _schema(self, ctx: ScoringContext) -> dict[str, Any] | None:
        model = self.params.get("model")
        if model is not None:
            if isinstance(model, str):
                module_name, attr = model.split(":", 1)
                model = getattr(importlib.import_module(module_name), attr)
            if isinstance(model, type) and issubclass(model, BaseModel):
                return model.model_json_schema()
            raise TypeError("model must be a Pydantic BaseModel subclass")
        if self.params.get("schema"):
            return self.params["schema"]
        if ctx.expected and isinstance(ctx.expected.get("schema"), dict):
            return ctx.expected["schema"]
        return None

    def score(self, ctx: ScoringContext) -> ScoreResult:
        schema = self._schema(ctx)
        if schema is None:
            return self.skip("No schema configured")
        try:
            value = get_path(ctx.actual, self.params.get("field"))
        except (KeyError, IndexError):
            return self.result(0.0, "Field to validate is missing")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return self.result(0.0, "Output is not valid JSON")
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(value), key=lambda e: list(e.path))
        if not errors:
            return self.result(1.0, "Output conforms to schema")
        messages = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:10]]
        return self.result(0.0, f"{len(errors)} schema violation(s): " + "; ".join(messages), errors=messages)
