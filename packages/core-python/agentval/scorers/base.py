"""Scorer base class and the modular scorer registry."""

from __future__ import annotations

import importlib
import inspect
from abc import ABC, abstractmethod
from typing import Any, Callable

from pydantic import BaseModel, Field


class ScoreResult(BaseModel):
    """Outcome of a single scorer on a single test case."""

    name: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    rationale: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False
    weight: float = 1.0


class ScoringContext(BaseModel):
    """Everything a scorer may look at."""

    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] | None = None
    actual: Any = None
    trace: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None


class Scorer(ABC):
    """Base scorer. Subclasses implement :meth:`score` (sync or async)."""

    name: str = "scorer"

    def __init__(self, weight: float = 1.0, threshold: float = 0.5, **params: Any) -> None:
        self.weight = float(weight)
        self.threshold = float(threshold)
        self.params = params

    @abstractmethod
    def score(self, ctx: ScoringContext) -> ScoreResult | Any:  # may return an awaitable
        ...

    async def ascore(self, ctx: ScoringContext) -> ScoreResult:
        result = self.score(ctx)
        if inspect.isawaitable(result):
            result = await result
        result.weight = self.weight
        return result

    def result(self, score: float, rationale: str = "", **details: Any) -> ScoreResult:
        score = max(0.0, min(1.0, float(score)))
        return ScoreResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            rationale=rationale,
            details=details,
            weight=self.weight,
        )

    def skip(self, reason: str) -> ScoreResult:
        return ScoreResult(
            name=self.name, score=0.0, passed=True, rationale=reason, skipped=True, weight=self.weight
        )


_REGISTRY: dict[str, type[Scorer]] = {}


def register_scorer(name: str) -> Callable[[type[Scorer]], type[Scorer]]:
    """Class decorator registering a scorer under ``name``."""

    def deco(cls: type[Scorer]) -> type[Scorer]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def available_scorers() -> list[str]:
    return sorted(_REGISTRY)


def get_scorer_class(type_: str) -> type[Scorer]:
    if type_ in _REGISTRY:
        return _REGISTRY[type_]
    if ":" in type_:  # custom plugin, e.g. "my_pkg.scorers:ToxicityScorer"
        module_name, attr = type_.split(":", 1)
        cls = getattr(importlib.import_module(module_name), attr)
        if not (inspect.isclass(cls) and issubclass(cls, Scorer)):
            raise TypeError(f"{type_} is not a Scorer subclass")
        return cls
    raise KeyError(f"Unknown scorer '{type_}'. Available: {', '.join(available_scorers())}")


def build_scorer(spec: dict[str, Any] | str) -> Scorer:
    """Build a scorer from ``{"type": ..., "weight": ..., "threshold": ..., "params": {...}}``."""
    if isinstance(spec, str):
        spec = {"type": spec}
    cls = get_scorer_class(spec["type"])
    kwargs = dict(spec.get("params") or {})
    for key in ("weight", "threshold"):
        if key in spec:
            kwargs[key] = spec[key]
    return cls(**kwargs)


def get_path(obj: Any, path: str | None) -> Any:
    """Resolve a dotted path (``a.b.0.c``) inside nested dicts/lists. ``None`` returns obj."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(path)
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        else:
            raise KeyError(path)
    return cur
