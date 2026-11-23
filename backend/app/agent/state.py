from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # short-term memory (checkpointed per thread)
    intent: str
    active_agent: str
    last_products: list[dict]
    pending_order: dict | None
    delivery: dict
    profile: dict
    blocked_reason: str | None
    steps: int
    turn_tool_calls: list[dict]
    turn_tokens: dict[str, int]
    reply: str
    meta: dict[str, Any]
