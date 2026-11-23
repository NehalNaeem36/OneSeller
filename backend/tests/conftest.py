"""Test fixtures: isolated SQLite DB per session, schema reset per test, scripted fake LLM (no network)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="oneseller-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["LLM_PROVIDER"] = "ollama"  # never anthropic in tests; the fake model is injected below
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["RATE_LIMIT_CHAT_PER_MINUTE"] = "1000"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "1000"

import io
import uuid
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agent import llm, runner
from app.db import Base, engine
from app.main import app
from app.ratelimit import limiter


class ScriptedModel(BaseChatModel):
    """Fake chat model. `script` maps (system_prompt, messages, bound_tool_names) -> AIMessage."""

    script: Callable[[str, list[BaseMessage], list[str]], AIMessage]
    tool_names: list[str] = []
    calls: list[dict] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self.model_copy(update={"tool_names": [t.__name__ for t in tools]})

    def bind(self, **kwargs):  # type: ignore[override]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        system = str(messages[0].content) if messages else ""
        msg = self.script(system, messages, self.tool_names)
        msg.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        ScriptedModel.calls.append({"system": system[:40], "tools": list(self.tool_names)})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}])


def last_tool_result(messages: list[BaseMessage]) -> str | None:
    from langchain_core.messages import ToolMessage
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            return str(m.content)
        if m.type == "human":
            return None
    return None


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limiter.reset()
    yield
    llm.set_test_model(None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_llm():
    def install(script):
        ScriptedModel.calls = []
        llm.set_test_model(ScriptedModel(script=script))
        return ScriptedModel
    return install


# ---------------------------------------------------------------- API helpers

def register(client, role: str, email: str | None = None, store_name: str | None = None) -> dict:
    email = email or f"{role}-{uuid.uuid4().hex[:6]}@test.io"
    body = {"email": email, "password": "password123", "full_name": f"Test {role}", "role": role}
    if role == "seller":
        body["store_name"] = store_name or f"Store {uuid.uuid4().hex[:4]}"
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    data["headers"] = {"Authorization": f"Bearer {data['token']}"}
    return data


def make_product(client, seller, **overrides) -> dict:
    body = {"name": "Black Cotton Shirt", "category": "Shirts", "price": 2500, "stock": 10,
            "colors": ["black"], "sizes": ["S", "M", "L"]}
    body.update(overrides)
    r = client.post("/api/seller/products", json=body, headers=seller["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def checkout(client, customer, key: str | None = None, confirm: bool = True):
    return client.post("/api/checkout", headers=customer["headers"] | {"Idempotency-Key": key or uuid.uuid4().hex},
                       json={"confirm": confirm, "delivery": {"customer_name": "Ali", "phone": "03001234567",
                                                              "address": "House 1, Street 2", "city": "Lahore"}})


def csv_bytes(rows: list[list]) -> io.BytesIO:
    import csv
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return io.BytesIO(buf.getvalue().encode())


@pytest.fixture
def restart_agent():
    """Simulate a server restart: drop the compiled graph and its checkpointer connection."""
    def _restart():
        runner.reset_graph()
    return _restart
