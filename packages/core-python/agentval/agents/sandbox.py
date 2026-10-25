"""Deterministic customer-service tool sandbox shared by the mock and LiteLLM agents.

Tools operate on the test case's ``input.context`` (initial environment state, e.g. ``orders``),
so every agent - mock or real model - sees exactly the same simulated backend.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _stable_int(key: str, lo: int, hi: int) -> int:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return lo + h % (hi - lo + 1)


def _fn(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "lookup_order": _fn("lookup_order", "Look up an order's status, carrier, tracking number, ETA and total.",
                        {"order_id": {**_S, "description": "Order id, e.g. A1001"}}, ["order_id"]),
    "issue_refund": _fn("issue_refund", "Issue a full refund for an order.",
                        {"order_id": _S, "reason": {**_S, "description": "e.g. damaged, not_delivered"}}, ["order_id", "reason"]),
    "send_password_reset": _fn("send_password_reset", "Email the customer a password reset link.",
                               {"email": _S}, ["email"]),
    "update_shipping_address": _fn("update_shipping_address", "Change the shipping address of an order that has not shipped yet.",
                                   {"order_id": _S, "address": _S}, ["order_id", "address"]),
    "create_ticket": _fn("create_ticket", "Open a ticket with a specialist team (e.g. queue 'carrier_redirect', 'billing').",
                         {"order_id": _S, "queue": _S, "summary": _S}, ["queue", "summary"]),
    "escalate_to_human": _fn("escalate_to_human", "Hand the conversation to a senior human specialist.",
                             {"reason": _S, "priority": {"type": "string", "enum": ["low", "normal", "high"]}}, ["reason"]),
}

TOOLS = set(TOOL_SCHEMAS)


def execute_tool(name: str, args: dict[str, Any], ctx: dict[str, Any]) -> tuple[Any, str, str | None]:
    """Run a sandbox tool. Returns ``(output, status, error)``; status is "ok" or "error"."""
    orders = ctx.get("orders", {})
    if name not in TOOLS:
        return None, "error", f"Unknown tool '{name}'"
    if name == "lookup_order":
        out = orders.get(args.get("order_id"))
        return (out, "ok", None) if out is not None else (None, "error", "Order not found")
    if name == "issue_refund":
        order = orders.get(args.get("order_id"))
        if order is None:
            return None, "error", "Order not found"
        return {"refund_id": f"RF-{args.get('order_id')}", "amount": order.get("total"), "status": "processed",
                "eta": "3-5 business days"}, "ok", None
    if name == "send_password_reset":
        return {"sent": True, "to": args.get("email"), "expires_minutes": 30}, "ok", None
    if name == "update_shipping_address":
        order = orders.get(args.get("order_id"), {})
        if order.get("status") in {"shipped", "delivered"}:
            return None, "error", "Cannot change address: order already shipped"
        return {"updated": True}, "ok", None
    if name == "create_ticket":
        return {"ticket_id": "TCK-" + str(_stable_int(str(sorted(args.items())), 1000, 9999)),
                "queue": args.get("queue", "support")}, "ok", None
    return {"handoff": True, "queue": "tier2", "specialist": "senior specialist", "eta_minutes": 5}, "ok", None
