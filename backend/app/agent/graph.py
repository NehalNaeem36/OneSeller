"""LangGraph workflow: load_context → guard → intent_router → {catalog|sales|order}_agent ⇄ tools → finalize."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from ..db import SessionLocal
from ..services import catalog, memory
from . import guard, prompts, tools
from .llm import clean_text, invoke_llm
from .state import AgentState

log = logging.getLogger("oneseller.agent")

AGENT_PROMPTS = {"catalog_agent": prompts.CATALOG, "sales_agent": prompts.SALES, "order_agent": prompts.ORDER}


def _cfg(config: RunnableConfig) -> dict:
    return config.get("configurable", {})


def _last_human(state: AgentState) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


def _add_tokens(state: AgentState, t: dict) -> dict:
    cur = dict(state.get("turn_tokens") or {"in": 0, "out": 0})
    return {"in": cur.get("in", 0) + t.get("in", 0), "out": cur.get("out", 0) + t.get("out", 0)}


# ------------------------------------------------------------------ nodes

def load_context(state: AgentState, config: RunnableConfig) -> dict:
    cfg = _cfg(config)
    principal = cfg["principal"]
    text = _last_human(state)
    s = get_settings()
    with SessionLocal() as db:
        # Long-term memory: persist explicitly stated preferences, then load the profile.
        if not guard.screen(text, s.max_chat_message_chars):
            for key, value in memory.extract_preferences(text).items():
                try:
                    memory.remember(db, principal, key, value, replace=(key == "budget_max"))
                except ValueError:
                    pass
        profile = memory.load(db, principal)
    update: dict = {"profile": profile, "meta": {"cart_at_turn_start": _cart_line(principal)}, "turn_tool_calls": [], "turn_tokens": {"in": 0, "out": 0}, "steps": 0,
                    "blocked_reason": None, "reply": "", "intent": "", "active_agent": ""}
    if not state.get("delivery"):
        update["delivery"] = tools.delivery_from_profile(principal)
    msgs = state.get("messages", [])
    if len(msgs) > s.agent_prune_after_messages:  # bound checkpoint growth
        keep = s.agent_prune_after_messages // 2
        update["messages"] = [RemoveMessage(id=m.id) for m in msgs[:-keep] if m.id]
    return update


def guard_node(state: AgentState) -> dict:
    reason = guard.screen(_last_human(state), get_settings().max_chat_message_chars)
    return {"blocked_reason": reason}


ORDER_KW = re.compile(r"\b(cart|basket|checkout|check out|orders?|create_order|place (an |the |my )?order|buy (it|this|that|them|now)|"
                      r"purchase|add (it|this|that|them|the|one|to)|remove|delete from|my orders?|order status|"
                      r"track|deliver(y)? (to|address|details)|my (name|phone|address|number) is|ship to)\b", re.I)
ADD_RE = re.compile(r"\badd\b", re.I)
CHECKOUT_KW = re.compile(r"\b(check ?out|place (an |the |my )?order|proceed to (pay|payment|checkout)|"
                         r"complete (the |my )?(order|purchase)|buy (it |them )?now|confirm (my |the )?order)\b", re.I)
DETAILS_RE = re.compile(r"\b(my name is|name:|phone|mobile|number is|address|deliver(y)? to|ship to|city)\b", re.I)
CHECKOUT_TALK = re.compile(r"\b(confirm|checkout|check out|place (the|your) order|order summary)\b", re.I)


def _last_ai_mentions_checkout(state: AgentState) -> bool:
    for m in reversed(state.get("messages", [])[:-1]):
        if isinstance(m, AIMessage) and not m.tool_calls:
            return bool(CHECKOUT_TALK.search(clean_text(m.content)))
    return False
SALES_KW = re.compile(r"\b(compare|comparison|cheaper|cheapest|expensive|difference|differ|better|best|recommend|"
                      r"suggest|which (one|is)|vs\.?|versus|prefer|favou?rite|remember|my (usual|typical)|"
                      r"hello|hi|hey|salam|thanks|thank you|help|what can you)\b", re.I)
CATALOG_KW = re.compile(r"\b(show|find|search|look(ing)? for|have|available|availability|in stock|stock|price|cost|"
                        r"how much|size|sizes|colou?rs?|under|below|store|stores|shop|details|tell me about|"
                        r"any|need|want|get)\b", re.I)


def intent_router(state: AgentState, config: RunnableConfig) -> dict:
    text = _last_human(state)
    pending = state.get("pending_order")
    if pending and guard.is_affirmative(text):
        return {"intent": "confirm", "active_agent": "order_agent"}
    if pending and guard.is_negative(text):
        return {"intent": "cancel_checkout", "active_agent": "order_agent", "pending_order": None}
    if CHECKOUT_KW.search(text) and not DETAILS_RE.search(text):
        return {"intent": "checkout", "active_agent": "order_agent"}
    if guard.is_affirmative(text) and _last_ai_mentions_checkout(state):
        return {"intent": "checkout", "active_agent": "order_agent"}  # "yes" with no live summary → rebuild it
    if ORDER_KW.search(text) or (ADD_RE.search(text) and state.get("last_products")):
        return {"intent": "order", "active_agent": "order_agent"}
    if SALES_KW.search(text):
        return {"intent": "sales", "active_agent": "sales_agent"}
    if CATALOG_KW.search(text) or catalog.parse_free_text(text) or catalog.keyword_tokens(text):
        # Product-ish words present. Short follow-ups ("and in blue?") also land here.
        return {"intent": "catalog", "active_agent": "catalog_agent"}
    # Ambiguous → cheap one-word LLM classification.
    msg, tok = invoke_llm([SystemMessage(prompts.ROUTER), HumanMessage(text[:500])],
                          principal=_cfg(config).get("principal"), max_tokens=5)
    label = clean_text(msg.content).lower()
    agent = next((a for a in ("catalog", "sales", "order") if a in label), None)
    tokens = _add_tokens(state, tok)
    if not agent:
        return {"intent": "out_of_scope", "active_agent": "", "blocked_reason": "off_topic", "turn_tokens": tokens}
    return {"intent": agent, "active_agent": f"{agent}_agent", "turn_tokens": tokens}


def _cart_line(principal: str) -> str:
    from ..services import cart as cart_svc
    with SessionLocal() as db:
        out = cart_svc.cart_out(cart_svc.get_or_create_cart(db, principal))
        db.commit()
    if not out["items"]:
        return "empty"
    return "; ".join(f"{i['quantity']} x #{i['product_id']} {i['name']}" for i in out["items"]) + f" (total Rs. {out['total']:,.0f})"


def _context_block(state: AgentState, agent: str, principal: str = "") -> str:
    parts = [f"Customer's saved preferences (long-term memory): {memory.profile_text(state.get('profile') or {})}"]
    last = state.get("last_products") or []
    if last:
        cheapest = min(last, key=lambda r: r["price"])["id"]
        priciest = max(last, key=lambda r: r["price"])["id"]
        lines = []
        for i, p in enumerate(last, 1):
            tag = " (cheapest)" if p["id"] == cheapest and len(last) > 1 else (
                " (most expensive)" if p["id"] == priciest and len(last) > 1 else "")
            lines.append(f"{i}. #{p['id']} {p['name']} - Rs. {p['price']:,.0f} - sizes {','.join(p['sizes']) or 'n/a'}"
                         f" - colors {','.join(p['colors']) or 'n/a'} - stock {p['stock']} - {p['store']}{tag}")
        parts.append("Recently shown products (authoritative, from earlier tool results):\n" + "\n".join(lines))
    else:
        parts.append("Recently shown products: none yet.")
    if agent == "order_agent":
        parts.append("Cart before the customer's latest message: " + (state.get("meta") or {}).get("cart_at_turn_start", "unknown")
                     + " (tool results in this turn show any changes since)")
        d = state.get("delivery") or {}
        parts.append("Delivery details collected: " + (json.dumps(d) if d else "none"))
        if state.get("intent") == "cancel_checkout":
            parts.append("The customer declined the checkout summary. Acknowledge that no order was placed.")
    return "\n\n".join(parts)


def _build_messages(state: AgentState, agent: str, principal: str = "") -> list:
    msgs = state.get("messages", [])
    idx = max((i for i, m in enumerate(msgs) if isinstance(m, HumanMessage)), default=0)
    history = [m for m in msgs[:idx]
               if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and not m.tool_calls and m.content)]
    history = history[-get_settings().agent_history_messages:]
    system = SystemMessage(AGENT_PROMPTS[agent] + "\n\n" + _context_block(state, agent, principal))
    return [system, *history, *msgs[idx:]]


def _last_tool_result(state: AgentState, name: str) -> dict | None:
    msgs = state.get("messages", [])
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            return None
        if isinstance(m, ToolMessage) and m.name == name:
            try:
                return json.loads(str(m.content).removeprefix("<tool_data>").removesuffix("</tool_data>"))
            except json.JSONDecodeError:
                return None
    return None


def _fmt_money(v: float) -> str:
    return f"Rs. {v:,.0f}"


def _checkout_template(res: dict) -> str | None:
    status = res.get("status")
    if status == "needs_details":
        labels = {"customer_name": "full name", "phone": "phone number", "address": "delivery address", "city": "city"}
        need = ", ".join(labels[m] for m in res["missing"])
        return (f"Your cart total is {_fmt_money(res['cart']['total'])}. To place the order I still need your {need}. "
                "Please share them.")
    if status == "awaiting_confirmation":
        lines = "\n".join(f"- {i['quantity']} x {i['name']}"
                          + (f" ({', '.join(x for x in (i['color'], i['size']) if x)})" if i['color'] or i['size'] else "")
                          + f" — {_fmt_money(i['subtotal'])} ({i['store']})" for i in res["cart"]["items"])
        d = res["delivery"]
        note = "\n(Test order via public API: no real stock is reserved.)" if res.get("sandbox") else ""
        return (f"Please review your order:\n{lines}\nTotal: {_fmt_money(res['cart']['total'])} — mock payment, "
                f"no real money is charged.\nDeliver to: {d.get('customer_name')}, {d.get('phone')}, "
                f"{d.get('address')}, {d.get('city')}.{note}\n\nReply **yes** to place the order or **no** to cancel.")
    if status == "empty_cart":
        return "Your cart is empty, so there's nothing to check out yet. Tell me what you're looking for and I'll help you find it."
    if status == "cart_issues":
        return "Some items in your cart need attention before checkout: " + "; ".join(res.get("issues", [])) + "."
    return None


def _order_template(res: dict) -> str:
    if not res.get("ok"):
        return f"I couldn't place the order: {res.get('message', 'please try checkout again')}. No order was created."
    parts = [f"Order #{o['order_id']} from {o['store']} — {_fmt_money(o['total'])} ({', '.join(o['items'])})"
             for o in res["orders"]]
    return ("Your order is confirmed! ✅\n" + "\n".join(parts) +
            f"\nGrand total: {_fmt_money(res['grand_total'])}. Status: confirmed. You'll find it in your order history.")


def make_agent_node(agent: str):
    def node(state: AgentState, config: RunnableConfig) -> dict:
        cfg = _cfg(config)
        steps = state.get("steps", 0)

        if agent == "order_agent":
            # Deterministic, zero-token paths for the safety-critical checkout steps.
            created = _last_tool_result(state, "create_order")
            if created is not None:
                return {"messages": [AIMessage(_order_template(created))]}
            prepared = _last_tool_result(state, "prepare_checkout")
            if prepared is not None and (text := _checkout_template(prepared)):
                return {"messages": [AIMessage(text)]}
            delivered = _last_tool_result(state, "set_delivery_details")
            if delivered and delivered.get("ok") and not delivered.get("missing") and prepared is None:
                return {"messages": [AIMessage("", tool_calls=[{"name": "prepare_checkout", "id": f"auto_prep_{steps}",
                                                                "args": {}}])], "steps": steps + 1}
            if state.get("intent") == "checkout" and steps == 0:
                return {"messages": [AIMessage("", tool_calls=[{"name": "prepare_checkout", "id": "checkout_1",
                                                                "args": {}}])], "steps": steps + 1}
            if state.get("intent") == "confirm" and steps == 0:
                token = (state.get("pending_order") or {}).get("token", "")
                return {"messages": [AIMessage("", tool_calls=[{"name": "create_order", "id": "confirm_1",
                                                                "args": {"confirmation_token": token}}])],
                        "steps": steps + 1}

        bound = tools.AGENT_TOOLS[agent] if steps < get_settings().agent_max_tool_steps else None
        msg, tok = invoke_llm(_build_messages(state, agent, cfg.get("principal", "")), bound, principal=cfg.get("principal"))
        if not bound and msg.tool_calls:
            msg = AIMessage(clean_text(msg.content) or "Sorry, I couldn't complete that. Could you rephrase?")
        return {"messages": [msg], "turn_tokens": _add_tokens(state, tok), "steps": steps + (1 if msg.tool_calls else 0)}

    node.__name__ = agent
    return node


def tool_node(state: AgentState, config: RunnableConfig) -> dict:
    cfg = _cfg(config)
    last = state["messages"][-1]
    agent = state.get("active_agent", "")
    snapshot = {k: state.get(k) for k in ("pending_order", "delivery", "last_products", "profile")}
    ctx = tools.ToolContext(principal=cfg["principal"], channel=cfg.get("channel", "agent"),
                            sandbox=cfg.get("sandbox", True), customer_id=cfg.get("customer_id"),
                            user_message=_last_human(state), state=snapshot)
    out_msgs, calls = [], list(state.get("turn_tool_calls") or [])
    for tc in last.tool_calls:
        result = tools.execute(tc["name"], tc.get("args") or {}, agent, ctx)
        ctx.state.update(ctx.updates)  # later calls in the same batch see earlier updates
        calls.append({"name": tc["name"], "args": tc.get("args") or {}, "agent": agent, "ok": bool(result.get("ok"))})
        out_msgs.append(ToolMessage(content=tools.dump(result), tool_call_id=tc["id"], name=tc["name"]))
    update: dict = {"messages": out_msgs, "turn_tool_calls": calls}
    for k in ("pending_order", "delivery", "last_products", "profile"):
        if k in ctx.updates:
            update[k] = ctx.updates[k]
    return update


def refuse(state: AgentState) -> dict:
    reason = state.get("blocked_reason") or "off_topic"
    return {"messages": [AIMessage(guard.REFUSALS.get(reason, guard.REFUSALS["off_topic"]))]}


ORDER_CLAIM_RE = re.compile(r"\border\b[^.!?\n]{0,40}\b(is |has been |was )?(confirmed|placed|successful|complete[d]?)\b|"
                            r"\border (id|number|no\.?)\s*[:#]?\s*#?\w*\d|#ORD", re.I)
SAFE_ORDER_REPLY = ("I haven't placed any order yet. To order, say \"checkout\" and I'll show you a summary of your cart "
                    "and delivery details; the order is only placed after you reply \"yes\" to that summary.")


def finalize(state: AgentState) -> dict:
    last = state["messages"][-1] if state.get("messages") else None
    text = clean_text(last.content) if isinstance(last, AIMessage) else ""
    placed = any(c["name"] == "create_order" and c.get("ok") for c in state.get("turn_tool_calls") or [])
    if text and not placed and ORDER_CLAIM_RE.search(text):
        log.warning("blocked unverified order claim: %r", text[:200])
        text = SAFE_ORDER_REPLY
    return {"reply": text or "Sorry, I couldn't come up with an answer. Could you rephrase your request?"}


# ------------------------------------------------------------------ routing

def after_guard(state: AgentState) -> str:
    return "refuse" if state.get("blocked_reason") else "intent_router"


def after_router(state: AgentState) -> str:
    return state.get("active_agent") or "refuse"


def after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else "finalize"


def after_tools(state: AgentState) -> str:
    return state.get("active_agent") or "finalize"


def build_graph(checkpointer):
    g = StateGraph(AgentState)
    g.add_node("load_context", load_context)
    g.add_node("guard", guard_node)
    g.add_node("intent_router", intent_router)
    for name in AGENT_PROMPTS:
        g.add_node(name, make_agent_node(name))
    g.add_node("tools", tool_node)
    g.add_node("refuse", refuse)
    g.add_node("finalize", finalize)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "guard")
    g.add_conditional_edges("guard", after_guard, ["refuse", "intent_router"])
    g.add_conditional_edges("intent_router", after_router, [*AGENT_PROMPTS, "refuse"])
    for name in AGENT_PROMPTS:
        g.add_conditional_edges(name, after_agent, ["tools", "finalize"])
    g.add_conditional_edges("tools", after_tools, [*AGENT_PROMPTS, "finalize"])
    g.add_edge("refuse", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


# ------------------------------------------------------------------ checkpointer

def make_checkpointer():
    s = get_settings()
    url = s.database_url
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[1]
        cp_path = str(Path(db_path).with_name(Path(db_path).stem + "_checkpoints.db"))
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(cp_path, check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        return saver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from langgraph.checkpoint.postgres import PostgresSaver
    # Direct (non-pooled) endpoint: setup() runs DDL and the saver uses prepared statements.
    direct = s.direct_database_url
    pg = direct.replace("postgresql+psycopg://", "postgresql://").replace("postgres://", "postgresql://")
    pool = ConnectionPool(pg, max_size=5, check=ConnectionPool.check_connection, max_idle=240,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=True)
    saver = PostgresSaver(pool)
    saver.setup()
    return saver
