"""Generic tool-calling agent backed by LiteLLM (OpenAI, Anthropic, Gemini, Ollama, ...).

API keys are read by LiteLLM from the environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...);
nothing is ever stored by AgentVal.

Test-case input contract:
  prompt:   user message
  system:   optional system prompt override
  tools:    list of OpenAI-style function tools (or plain names)
  context.tool_results: {tool_name: canned result}  # deterministic tool sandbox
"""

from __future__ import annotations

import json
import time
from typing import Any

from agentval.agents.base import Agent, TraceRecorder

DEFAULT_SYSTEM = (
    "You are a helpful customer service agent. Use tools when needed. When finished, reply with "
    'a JSON object: {"reply": str, "resolution": "resolved"|"escalated"|"needs_info", "actions": [str]}.'
)


def _tool_schema(tool: Any) -> dict[str, Any]:
    if isinstance(tool, str):
        return {"type": "function", "function": {"name": tool, "parameters": {"type": "object", "properties": {}}}}
    if "function" in tool:
        return tool
    return {"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""),
                                             "parameters": tool.get("parameters", {"type": "object", "properties": {}})}}


class LiteLLMToolAgent(Agent):
    name = "litellm-tool-agent"

    def __init__(self, model: str = "gpt-4o-mini", system_prompt: str | None = None,
                 max_iterations: int = 6, temperature: float = 0.0, **params: Any) -> None:
        super().__init__(**params)
        self.model = model
        self.system_prompt = system_prompt or DEFAULT_SYSTEM
        self.max_iterations = max_iterations
        self.temperature = temperature

    async def run(self, input: dict[str, Any], recorder: TraceRecorder) -> Any:
        import litellm

        recorder.add_step("input", "user_message", input=input)
        tools = [_tool_schema(t) for t in input.get("tools", [])]
        canned = (input.get("context") or {}).get("tool_results", {})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": input.get("system") or self.system_prompt},
            {"role": "user", "content": input.get("prompt", "")},
        ]
        recorder.messages = messages
        for i in range(self.max_iterations):
            t0 = time.perf_counter()
            resp = await litellm.acompletion(model=self.model, messages=messages,
                                             tools=tools or None, temperature=self.temperature)
            ms = (time.perf_counter() - t0) * 1000
            usage = getattr(resp, "usage", None)
            try:
                cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
            except Exception:  # unknown model pricing
                cost = 0.0
            msg = resp.choices[0].message
            recorder.add_step("llm", f"llm_call_{i + 1}", input={"messages": len(messages)},
                              output=msg.content or "[tool calls]", latency_ms=ms,
                              prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                              completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                              cost_usd=cost, attributes={"gen_ai.request.model": self.model})
            tool_calls = getattr(msg, "tool_calls", None) or []
            messages.append(msg.model_dump() if hasattr(msg, "model_dump") else dict(msg))
            if not tool_calls:
                content = msg.content or ""
                try:
                    output: Any = json.loads(content)
                except ValueError:
                    output = {"reply": content}
                recorder.add_step("output", "final_answer", output=output)
                return output
            for call in tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except ValueError:
                    args = {"_raw": call.function.arguments}
                known = name in canned or any(t["function"]["name"] == name for t in tools)
                result = canned.get(name, {"ok": True}) if known else {"error": f"unknown tool {name}"}
                recorder.add_step("tool_call", name, input=args, output=result,
                                  status="ok" if known else "error",
                                  error=None if known else f"Unknown tool '{name}'")
                messages.append({"role": "tool", "tool_call_id": call.id, "name": name,
                                 "content": json.dumps(result)})
        recorder.add_step("error", "max_iterations", status="error", error="Agent exceeded max_iterations")
        return {"reply": "", "resolution": "needs_info", "actions": []}
