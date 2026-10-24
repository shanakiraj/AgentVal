"""Deterministic mock customer-service agent. Needs NO API keys.

It simulates an LLM tool-using agent (planning "LLM" steps, tool calls against a fake
backend held in ``input.context``, latency, token usage and cost) so the whole AgentVal
pipeline can be demonstrated offline.

Variants:
  "improved" (default) - follows policy and the expected trajectory almost perfectly.
  "baseline"           - an older prompt with realistic mistakes: invalid tool calls,
                         skipped lookups, policy violations and a wrong resolution.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from agentval.agents.base import Agent, TraceRecorder

# Fake per-token pricing for the simulated model (USD per token).
MOCK_PRICING = {"prompt": 0.15 / 1_000_000, "completion": 0.60 / 1_000_000}

TOOLS = {"lookup_order", "issue_refund", "send_password_reset", "update_shipping_address",
         "create_ticket", "escalate_to_human"}


class TransientAgentError(RuntimeError):
    """Simulated transient failure (e.g. provider 429) used to exercise retries."""


def _tokens(text: Any) -> int:
    return max(1, len(str(text)) // 4)


def _jitter(key: str, lo: int, hi: int) -> int:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return lo + h % (hi - lo + 1)


class MockCustomerServiceAgent(Agent):
    name = "mock-customer-service"

    def __init__(self, variant: str = "improved", model: str = "mock/cs-agent-v2",
                 speed: float = 1.0, flaky: bool = False, **params: Any) -> None:
        super().__init__(**params)
        self.variant = variant
        self.model = model
        self.speed = float(speed)
        self.flaky = flaky
        self._attempts: dict[str, int] = {}

    # ------------------------------------------------------------------ helpers
    async def _sleep(self, ms: int) -> None:
        if self.speed > 0:
            await asyncio.sleep(ms / 1000 * self.speed)

    async def _llm(self, rec: TraceRecorder, name: str, prompt: str, thought: str) -> None:
        ms = _jitter(prompt + name + self.variant, 180, 650)
        await self._sleep(ms)
        pt, ct = _tokens(prompt) + 220, _tokens(thought) + 15
        cost = pt * MOCK_PRICING["prompt"] + ct * MOCK_PRICING["completion"]
        rec.messages.append({"role": "assistant", "content": thought})
        rec.add_step("llm", name, input={"prompt": prompt[:500]}, output=thought, latency_ms=ms,
                     prompt_tokens=pt, completion_tokens=ct, cost_usd=cost,
                     attributes={"gen_ai.request.model": self.model})

    async def _tool(self, rec: TraceRecorder, ctx: dict[str, Any], name: str, args: dict[str, Any]) -> Any:
        ms = _jitter(name + str(args), 40, 260)
        await self._sleep(ms)
        orders = ctx.get("orders", {})
        if name not in TOOLS:
            rec.add_step("tool_call", name, input=args, status="error", latency_ms=ms,
                         error=f"Unknown tool '{name}'")
            return None
        out: Any
        status, error = "ok", None
        if name == "lookup_order":
            out = orders.get(args.get("order_id"))
            if out is None:
                status, error = "error", "Order not found"
        elif name == "issue_refund":
            out = {"refund_id": f"RF-{args.get('order_id')}", "amount": orders.get(args.get("order_id"), {}).get("total"), "status": "processed"}
        elif name == "send_password_reset":
            out = {"sent": True, "to": args.get("email")}
        elif name == "update_shipping_address":
            order = orders.get(args.get("order_id"), {})
            if order.get("status") in {"shipped", "delivered"}:
                out, status, error = None, "error", "Cannot change address: order already shipped"
            else:
                out = {"updated": True}
        elif name == "create_ticket":
            out = {"ticket_id": "TCK-" + str(_jitter(str(args), 1000, 9999)), "queue": args.get("queue", "support")}
        else:  # escalate_to_human
            out = {"handoff": True, "queue": "tier2", "eta_minutes": 5}
        rec.messages.append({"role": "tool", "name": name, "content": out})
        rec.add_step("tool_call", name, input=args, output=out, status=status, error=error, latency_ms=ms)
        return out

    # ------------------------------------------------------------------ main loop
    async def run(self, input: dict[str, Any], recorder: TraceRecorder) -> Any:
        prompt: str = input.get("prompt", "")
        ctx: dict[str, Any] = input.get("context", {})
        recorder.messages.append({"role": "user", "content": prompt})
        recorder.add_step("input", "user_message", input=input)

        key = prompt[:40]
        self._attempts[key] = self._attempts.get(key, 0) + 1
        if self.flaky and self._attempts[key] == 1 and _jitter(key, 0, 2) == 0:
            raise TransientAgentError("Simulated 429 rate limit from model provider")

        text = prompt.lower()
        order_id = (re.search(r"\b([A-Z]\d{4})\b", prompt) or [None, None])[1]
        found = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", prompt)
        email = found.group(0) if found else ctx.get("customer", {}).get("email")
        baseline = self.variant == "baseline"

        if any(w in text for w in ("lawyer", "sue", "unacceptable", "furious")):
            await self._llm(recorder, "plan", prompt, "Customer is very upset and mentions legal action; escalate.")
            await self._tool(recorder, ctx, "escalate_to_human", {"reason": "legal_threat", "priority": "high"})
            reply = ("I'm truly sorry for the frustration. I've escalated this to a senior specialist "
                     "who will contact you within 5 minutes.")
            if baseline:
                reply = "Please calm down. " + reply
            return self._final(recorder, reply, "escalated", ["escalate_to_human"])

        if "password" in text or "log in" in text or "login" in text:
            await self._llm(recorder, "plan", prompt, "User is locked out; send a password reset link.")
            if baseline:
                await self._tool(recorder, ctx, "reset_password", {"email": email})  # invalid tool
            await self._tool(recorder, ctx, "send_password_reset", {"email": email})
            reply = f"I've sent a password reset link to {email}. It expires in 30 minutes."
            return self._final(recorder, reply, "resolved", ["send_password_reset"])

        if "refund" in text or "damaged" in text:
            await self._llm(recorder, "plan", prompt, f"Refund request for {order_id}; verify order then refund.")
            if baseline:
                await self._tool(recorder, ctx, "check_refund_policy", {"order_id": order_id})  # invalid tool
            else:
                await self._tool(recorder, ctx, "lookup_order", {"order_id": order_id})
            refund = await self._tool(recorder, ctx, "issue_refund", {"order_id": order_id, "reason": "damaged"})
            amount = (refund or {}).get("amount")
            reply = (f"I'm sorry your item arrived damaged. I've issued a full refund of ${amount} for order "
                     f"{order_id}; it should appear in 3-5 business days.")
            return self._final(recorder, reply, "resolved", ["issue_refund"])

        if "address" in text:
            await self._llm(recorder, "plan", prompt, f"Address change for {order_id}; check order status first.")
            if baseline:
                await self._tool(recorder, ctx, "update_shipping_address", {"order_id": order_id, "address": "new"})
                await self._llm(recorder, "respond", prompt, "Tell the customer the address was updated.")
                reply = f"Done! I've updated the shipping address for order {order_id}."
                return self._final(recorder, reply, "resolved", ["update_shipping_address"])
            order = await self._tool(recorder, ctx, "lookup_order", {"order_id": order_id}) or {}
            if order.get("status") in {"shipped", "delivered"}:
                ticket = await self._tool(recorder, ctx, "create_ticket", {"order_id": order_id, "queue": "carrier_redirect"})
                reply = (f"Order {order_id} has already shipped, so I can't change the address directly. "
                         f"I've opened ticket {ticket['ticket_id']} with our carrier team to request a redirect.")
                return self._final(recorder, reply, "escalated", ["create_ticket"])
            await self._tool(recorder, ctx, "update_shipping_address", {"order_id": order_id})
            return self._final(recorder, f"Updated the address for {order_id}.", "resolved", ["update_shipping_address"])

        # default: order status
        await self._llm(recorder, "plan", prompt, f"Order status question for {order_id}; look it up.")
        order = await self._tool(recorder, ctx, "lookup_order", {"order_id": order_id}) or {}
        if baseline:  # redundant second lookup + extra LLM turn (inefficient trajectory)
            await self._tool(recorder, ctx, "lookup_order", {"order_id": order_id})
            await self._llm(recorder, "reflect", prompt, "Double-check the order status.")
        reply = (f"Your order {order_id} is {order.get('status', 'unknown')} via {order.get('carrier', 'our carrier')}"
                 f" (tracking {order.get('tracking', 'n/a')}), arriving {order.get('eta', 'soon')}.")
        return self._final(recorder, reply, "resolved", [])

    def _final(self, rec: TraceRecorder, reply: str, resolution: str, actions: list[str]) -> dict[str, Any]:
        output = {"reply": reply, "resolution": resolution, "actions": actions}
        rec.messages.append({"role": "assistant", "content": reply})
        rec.add_step("output", "final_answer", output=output, completion_tokens=0)
        return output
