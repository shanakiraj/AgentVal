"""Generic tool-calling agent backed by LiteLLM (OpenAI, Anthropic, Gemini, Ollama, OpenRouter, ...).

API keys are read by LiteLLM from the environment (OPENAI_API_KEY, ANTHROPIC_API_KEY,
OPENROUTER_API_KEY, ...). AgentVal never stores keys or request headers: traces only contain
the chat messages, tool calls, token usage and timings.

Test-case input contract:
  prompt:   user message
  system:   optional system prompt override
  tools:    tool names from the built-in customer-service sandbox, or OpenAI-style function tools
  context:  initial environment state for the sandbox (e.g. ``orders``)
  context.tool_results: optional {tool_name: canned result} overriding the sandbox
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any

from agentval.agents.base import Agent, TraceRecorder
from agentval.agents.sandbox import TOOL_SCHEMAS, execute_tool

DEFAULT_SYSTEM = (
    "You are a helpful customer service agent. Use tools when needed. When finished, reply with "
    'ONLY a JSON object: {"reply": str, "resolution": "resolved"|"escalated"|"needs_info", "actions": [str]}.'
)

log = logging.getLogger("agentval.agents")

RETRYABLE = ("RateLimitError", "ServiceUnavailableError", "APIConnectionError", "Timeout", "InternalServerError",
             "BadGatewayError")


def _tool_schema(tool: Any) -> dict[str, Any]:
    if isinstance(tool, str):
        return TOOL_SCHEMAS.get(tool) or {"type": "function", "function": {
            "name": tool, "parameters": {"type": "object", "properties": {}}}}
    if "function" in tool:
        return tool
    return {"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""),
                                             "parameters": tool.get("parameters", {"type": "object", "properties": {}})}}


def parse_final(content: str) -> Any:
    """Parse the agent's final answer: JSON (optionally fenced / surrounded by prose) or plain text."""
    text = (content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    candidates.append(text)
    for c in candidates:
        try:
            value = json.loads(c)
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return {"reply": text}


def is_free_model(model: str) -> bool:
    return model.endswith(":free")


class LiteLLMToolAgent(Agent):
    name = "litellm-tool-agent"

    def __init__(self, model: str = "gpt-4o-mini", system_prompt: str | None = None,
                 max_iterations: int = 6, temperature: float = 0.0, max_tokens: int = 1024,
                 call_retries: int = 4, retry_base_delay: float = 4.0, request_timeout: float = 90.0,
                 **params: Any) -> None:
        super().__init__(**params)
        self.model = model
        self.system_prompt = system_prompt or DEFAULT_SYSTEM
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.call_retries = call_retries
        self.retry_base_delay = retry_base_delay
        self.request_timeout = request_timeout

    async def _complete(self, **kwargs: Any) -> tuple[Any, int]:
        """Call the model, retrying rate limits / transient errors with exponential backoff."""
        import litellm

        litellm.suppress_debug_info = True
        for attempt in range(self.call_retries + 1):
            try:
                return await litellm.acompletion(**kwargs), attempt
            except Exception as exc:  # noqa: BLE001
                if attempt >= self.call_retries or not any(r in type(exc).__name__ for r in RETRYABLE):
                    raise
                log.warning("%s: %s on attempt %d, backing off", self.model, type(exc).__name__, attempt + 1)
                await asyncio.sleep(self.retry_base_delay * (2**attempt) * (1 + random.random() * 0.25))
        raise RuntimeError("unreachable")

    def _cost(self, resp: Any) -> float:
        if is_free_model(self.model):
            return 0.0
        usage = getattr(resp, "usage", None)
        reported = getattr(usage, "cost", None) if usage is not None else None
        if isinstance(reported, (int, float)):
            return float(reported)
        try:
            import litellm

            return float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:  # unknown model pricing
            return 0.0

    async def run(self, input: dict[str, Any], recorder: TraceRecorder) -> Any:
        recorder.add_step("input", "user_message", input=input)
        tools = [_tool_schema(t) for t in input.get("tools", [])]
        tool_names = {t["function"]["name"] for t in tools}
        ctx = input.get("context") or {}
        canned = ctx.get("tool_results", {})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": input.get("system") or self.system_prompt},
            {"role": "user", "content": input.get("prompt", "")},
        ]
        recorder.messages = messages  # chat history only; no request headers or credentials
        for i in range(self.max_iterations):
            t0 = time.perf_counter()
            resp, retries = await self._complete(
                model=self.model, messages=messages, tools=tools or None, temperature=self.temperature,
                max_tokens=self.max_tokens, timeout=self.request_timeout)
            latency = (time.perf_counter() - t0) * 1000
            usage = getattr(resp, "usage", None)
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            recorder.add_step(
                "llm", f"llm_call_{i + 1}", input={"messages": len(messages)},
                output=msg.content or (f"[{len(tool_calls)} tool call(s)]" if tool_calls else ""),
                latency_ms=latency,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cost_usd=self._cost(resp),
                attributes={"gen_ai.request.model": self.model, "rate_limit_retries": retries,
                            "finish_reason": getattr(resp.choices[0], "finish_reason", None),
                            **({"reasoning": str(msg.reasoning_content)[:2000]}
                               if getattr(msg, "reasoning_content", None) else {})})
            assistant: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if tool_calls:
                assistant["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                    for c in tool_calls]
            messages.append(assistant)
            if not tool_calls:
                output = parse_final(msg.content or "")
                recorder.add_step("output", "final_answer", output=output)
                return output
            for call in tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except ValueError:
                    args = {"_raw": call.function.arguments}
                t1 = time.perf_counter()
                if name in canned:
                    result, status, error = canned[name], "ok", None
                elif name in tool_names and name in TOOL_SCHEMAS:
                    result, status, error = execute_tool(name, args, ctx)
                elif name in tool_names:
                    result, status, error = {"ok": True}, "ok", None
                else:
                    result, status, error = None, "error", f"Unknown tool '{name}'"
                recorder.add_step("tool_call", name, input=args, output=result, status=status, error=error,
                                  latency_ms=(time.perf_counter() - t1) * 1000)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": name,
                                 "content": json.dumps(result if status == "ok" else {"error": error})})
        recorder.add_step("error", "max_iterations", status="error", error="Agent exceeded max_iterations")
        return {"reply": "", "resolution": "needs_info", "actions": []}
