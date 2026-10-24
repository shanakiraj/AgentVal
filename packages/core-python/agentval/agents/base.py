"""Agent interface + trace recorder (OpenTelemetry-style spans flattened into steps)."""

from __future__ import annotations

import importlib
import inspect
import secrets
import time
from abc import ABC, abstractmethod
from typing import Any


def _span_id() -> str:
    return secrets.token_hex(8)


class TraceRecorder:
    """Collects the multi-step trajectory of one agent execution.

    Each step mirrors an OpenTelemetry span: ``spanId``, ``parentSpanId``, ``name``,
    ``startTimeUnixNano``/``endTimeUnixNano`` plus agent-specific attributes.
    Step ``type`` is one of: input, llm, tool_call, output, error.
    """

    def __init__(self) -> None:
        self.trace_id = secrets.token_hex(16)
        self.root_span_id = _span_id()
        self.steps: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0
        self._t0 = time.time_ns()

    def add_step(
        self,
        type: str,
        name: str,
        *,
        input: Any = None,
        output: Any = None,
        latency_ms: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        status: str = "ok",
        error: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        end = time.time_ns()
        start = end - int(latency_ms * 1_000_000)
        step = {
            "id": _span_id(),
            "parentId": self.root_span_id,
            "type": type,
            "name": name,
            "input": input,
            "output": output,
            "status": status,
            "error": error,
            "latencyMs": round(latency_ms, 2),
            # OTLP/JSON encodes 64-bit nanosecond timestamps as strings
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(end),
            "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
            "costUsd": cost_usd,
            "attributes": attributes or {},
        }
        self.steps.append(step)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.cost_usd += cost_usd
        return step

    def to_dict(self, *, attempts: int = 1, total_latency_ms: float | None = None) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "rootSpanId": self.root_span_id,
            "format": "agentval.trace.v1 (OpenTelemetry-compatible span fields)",
            "steps": self.steps,
            "messages": self.messages,
            "attempts": attempts,
            "totals": {
                "promptTokens": self.prompt_tokens,
                "completionTokens": self.completion_tokens,
                "costUsd": round(self.cost_usd, 8),
                "latencyMs": total_latency_ms,
                "steps": len(self.steps),
            },
        }


class Agent(ABC):
    """An agent under test. Implement :meth:`run`; record steps on ``recorder``."""

    name: str = "agent"
    model: str | None = None

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    async def run(self, input: dict[str, Any], recorder: TraceRecorder) -> Any:
        """Execute on one test-case input and return the final output."""


def build_agent(spec: dict[str, Any] | None) -> Agent:
    spec = dict(spec or {"type": "mock"})
    type_ = spec.pop("type", "mock")
    params = {**spec.pop("params", {}), **spec}
    if type_ == "mock":
        from agentval.agents.mock import MockCustomerServiceAgent

        return MockCustomerServiceAgent(**params)
    if type_ == "litellm":
        from agentval.agents.litellm_agent import LiteLLMToolAgent

        return LiteLLMToolAgent(**params)
    if ":" in type_:
        module_name, attr = type_.split(":", 1)
        cls = getattr(importlib.import_module(module_name), attr)
        if not (inspect.isclass(cls) and issubclass(cls, Agent)):
            raise TypeError(f"{type_} is not an Agent subclass")
        return cls(**params)
    raise KeyError(f"Unknown agent type '{type_}' (use 'mock', 'litellm' or 'module:Class')")
