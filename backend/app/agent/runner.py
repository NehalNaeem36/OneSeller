"""Turn execution: thread ownership, timeout, failure handling, and the /chat response shape."""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import ChatThread, utcnow
from ..services.usage import BudgetExceeded
from .graph import build_graph, make_checkpointer

log = logging.getLogger("oneseller.runner")
_graph = None
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent")


def get_graph():
    global _graph
    with _lock:
        if _graph is None:
            _graph = build_graph(make_checkpointer())
        return _graph


def reset_graph() -> None:
    """Drop the compiled graph (tests use this to simulate a server restart)."""
    global _graph
    with _lock:
        _graph = None


def checkpoint_key(principal: str, thread_id: str) -> str:
    # Namespaced by principal: the same thread_id from a different user maps to a different conversation,
    # so a thread can never be read or reassigned by submitting another user_id.
    return hashlib.sha256(f"{principal}:{thread_id}".encode()).hexdigest()[:40]


def _register_thread(principal: str, thread_id: str, key: str, message: str) -> None:
    with SessionLocal() as db:
        row = db.scalars(select(ChatThread).where(ChatThread.principal == principal,
                                                  ChatThread.thread_id == thread_id)).first()
        if row:
            row.updated_at = utcnow()
        else:
            db.add(ChatThread(principal=principal, thread_id=thread_id, checkpoint_key=key,
                              title=message.strip()[:60] or "New conversation"))
        db.commit()


def run_turn(principal: str, thread_id: str, message: str, *, channel: str, sandbox: bool,
             customer_id: int | None = None) -> dict:
    s = get_settings()
    key = checkpoint_key(principal, thread_id)
    _register_thread(principal, thread_id, key, message)
    config = {"configurable": {"thread_id": key, "principal": principal, "channel": channel,
                               "sandbox": sandbox, "customer_id": customer_id},
              "recursion_limit": 40}
    graph = get_graph()
    t0 = time.perf_counter()
    try:
        fut = _pool.submit(graph.invoke, {"messages": [HumanMessage(message)]}, config)
        state = fut.result(timeout=s.agent_turn_timeout_seconds)
        result = {"reply": state.get("reply") or "", "tool_calls": state.get("turn_tool_calls") or [],
                  "tokens": state.get("turn_tokens") or {"in": 0, "out": 0}}
    except FutureTimeout:
        log.error("agent turn timed out principal=%s", principal)
        result = _failure("Sorry, that took too long. Please try again.", graph, config)
    except BudgetExceeded as exc:
        result = _failure(exc.message, graph, config)
    except Exception:
        log.exception("agent turn failed principal=%s", principal)
        result = _failure("Sorry, the assistant is temporarily unavailable. Please try again in a moment.",
                          graph, config)
    result["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    log.info("turn principal=%s tools=%s tokens=%s %dms", principal,
             [c["name"] for c in result["tool_calls"]], result["tokens"], result["latency_ms"])
    return result


def _failure(reply: str, graph, config) -> dict:
    tokens, calls = {"in": 0, "out": 0}, []
    try:
        snap = graph.get_state(config).values
        tokens = snap.get("turn_tokens") or tokens
        calls = snap.get("turn_tool_calls") or calls
        graph.update_state(config, {"messages": [AIMessage(reply)]})  # keep the transcript well-formed
    except Exception:
        pass
    return {"reply": reply, "tool_calls": calls, "tokens": tokens}


def thread_messages(principal: str, thread_id: str) -> list[dict]:
    graph = get_graph()
    snap = graph.get_state({"configurable": {"thread_id": checkpoint_key(principal, thread_id)}})
    out = []
    for m in (snap.values or {}).get("messages", []):
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": str(m.content)})
        elif isinstance(m, AIMessage) and not m.tool_calls and m.content:
            from .llm import clean_text
            out.append({"role": "assistant", "content": clean_text(m.content)})
    return out
