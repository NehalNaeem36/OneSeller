"""Provider-independent chat-model adapter.

Business logic only ever calls `invoke_llm()`. Switching between Ollama (local Qwen) and Anthropic
(claude-haiku-5-5) is a pure configuration change (LLM_PROVIDER). Every call is metered, and calls to a
paid provider are refused up front when the spending guard says the budget would be exceeded.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

from ..config import get_settings
from ..services import usage

log = logging.getLogger("oneseller.llm")
_override: BaseChatModel | None = None
_cache: dict[str, BaseChatModel] = {}


def set_test_model(model: BaseChatModel | None) -> None:
    """Tests inject a scripted model here (no network)."""
    global _override
    _override = model


def provider_name() -> str:
    return "fake" if _override is not None else get_settings().llm_provider


def model_name() -> str:
    s = get_settings()
    p = provider_name()
    return {"anthropic": s.anthropic_model, "ollama": s.ollama_model}.get(p, "fake")


def _build() -> BaseChatModel:
    s = get_settings()
    if s.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        # claude-haiku-5-5: no sampling params (non-default temperature is rejected); thinking off for a
        # short, cheap, latency-sensitive sales chat (allowed at the default effort level).
        return ChatAnthropic(model=s.anthropic_model, api_key=s.anthropic_api_key,
                             max_tokens=s.llm_max_output_tokens, max_retries=s.llm_max_retries,
                             default_request_timeout=s.llm_timeout_seconds,
                             thinking={"type": "disabled"})
    if s.llm_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=s.ollama_model, base_url=s.ollama_base_url, temperature=0,
                          num_ctx=s.ollama_num_ctx, num_predict=s.llm_max_output_tokens,
                          reasoning=False, keep_alive="30m")
    raise RuntimeError(f"Unknown LLM_PROVIDER: {s.llm_provider}")


def get_model() -> BaseChatModel:
    if _override is not None:
        return _override
    key = get_settings().llm_provider
    if key not in _cache:
        _cache[key] = _build()
    return _cache[key]


THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def clean_text(text: Any) -> str:
    if isinstance(text, list):  # content blocks
        text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in text)
    return THINK_RE.sub("", str(text or "")).replace("<think>", "").replace("</think>", "").strip()


def invoke_llm(messages: list[BaseMessage], tools: list | None = None, *, principal: str | None = None,
               max_tokens: int | None = None) -> tuple[AIMessage, dict]:
    provider = provider_name()
    usage.check_budget(provider)
    model = get_model()
    runnable: Any = model
    if tools:
        runnable = model.bind_tools(tools)
    if max_tokens and provider == "anthropic":
        runnable = runnable.bind(max_tokens=max_tokens)
    elif max_tokens and provider == "ollama":
        runnable = runnable.bind(options={"num_predict": max_tokens})

    attempts = 2 if provider == "ollama" else 1  # Anthropic SDK already retries transient errors
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            t0 = time.perf_counter()
            msg: AIMessage = runnable.invoke(messages)
            meta = getattr(msg, "usage_metadata", None) or {}
            tin, tout = int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))
            cost = usage.record(provider, model_name(), tin, tout, principal) if provider != "fake" else 0.0
            log.info("llm call provider=%s in=%d out=%d cost=%.6f %.2fs", provider, tin, tout, cost,
                     time.perf_counter() - t0)
            return msg, {"in": tin, "out": tout}
        except usage.BudgetExceeded:
            raise
        except Exception as exc:  # transient local-model hiccup → one retry
            last_exc = exc
            log.warning("llm call failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(0.5)
    raise RuntimeError(f"LLM unavailable: {last_exc}") from last_exc
