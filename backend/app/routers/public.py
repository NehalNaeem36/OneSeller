"""Mandatory grading API. Contract is frozen: POST /chat → {reply, tool_calls, tokens:{in,out}}; GET /health → ok."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ..agent.runner import run_turn
from ..config import get_settings
from ..ratelimit import client_ip, limiter
from ..schemas import ChatRequest

router = APIRouter()


@router.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


@router.post("/chat")
def chat(body: ChatRequest, request: Request) -> dict:
    s = get_settings()
    limiter.hit(f"chat-ip:{client_ip(request)}", s.rate_limit_chat_per_minute)
    limiter.hit(f"chat-user:{body.user_id}", s.rate_limit_chat_per_minute)
    # Unauthenticated: user_id only scopes a sandboxed benchmark namespace ("api:*"), never real accounts.
    result = run_turn(f"api:{body.user_id}", body.thread_id, body.message, channel="public_api", sandbox=True)
    return {"reply": result["reply"], "tool_calls": result["tool_calls"],
            "tokens": {"in": int(result["tokens"].get("in", 0)), "out": int(result["tokens"].get("out", 0))}}
