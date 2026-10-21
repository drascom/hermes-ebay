"""Hermes eBay read-only seller monitoring plugin."""
from __future__ import annotations

import json

from . import ebay_client as api
from .ebay_cli import handle_cli, setup_cli

TOOLSET = "ebay"


def _handler(fn):
    def wrapped(args, **kwargs):
        del kwargs
        try:
            return json.dumps({"success": True, "data": fn(args)}, separators=(",", ":"))
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)}, separators=(",", ":"))
    return wrapped


def _schema(name: str, description: str, properties: dict | None = None) -> dict:
    return {"name": name, "description": description, "parameters": {"type": "object", "properties": properties or {}, "additionalProperties": False}}


TOOLS = (
    ("ebay_account_status", "Read eBay seller registration and selling-limit status.", api.account_status, {}),
    ("ebay_orders", "List recent eBay orders with buyer PII omitted.", api.orders, {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7}, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}),
    ("ebay_offers", "List inventory offers; never creates or changes listings.", api.offers, {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}),
    ("ebay_returns", "List return cases without buyer PII.", api.returns, {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}),
    ("ebay_cancellations", "List cancellation requests without buyer PII.", api.cancellations, {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}}),
    ("ebay_monitor_status", "Show OAuth and deduplicating monitor status without exposing credentials or tokens.", api.monitor_status, {}),
)


def register(ctx) -> None:
    for name, description, fn, properties in TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=_schema(name, description, properties), handler=_handler(fn), emoji="🛒")
    ctx.register_cli_command(name="ebay", help="Set up eBay OAuth and opt-in seller alerts", description="Read-only eBay seller monitoring.", setup_fn=setup_cli, handler_fn=handle_cli)


__all__ = ["register"]
