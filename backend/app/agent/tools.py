"""Agent tools.

Each tool = a Pydantic argument model (its class name is the tool name, its docstring the description; this
is what the LLM sees) + a DB-backed implementation. Implementations receive a `ToolContext` built by the
server from graph config — identity is never an LLM-controllable argument.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..errors import AppError
from ..models import Order, Product, Store, User
from ..services import cart as cart_svc, catalog, memory, orders as order_svc
from . import guard


@dataclass
class ToolContext:
    principal: str
    channel: str                 # "agent" (website) | "public_api"
    sandbox: bool                # public API → sandbox orders
    customer_id: int | None
    user_message: str            # latest human message (for the confirmation gate)
    state: dict                  # read-only snapshot of graph state
    updates: dict = field(default_factory=dict)  # state updates produced by tools


# ------------------------------------------------------------------ schemas (LLM-visible)

class search_products(BaseModel):
    """Search the live product catalog. Use for any product lookup. Put product words (e.g. 'shirt') in query and
    use the dedicated filter fields for color, size and price. Returns real products with prices and stock."""
    query: Optional[str] = Field(None, description="Product keywords, e.g. 'cotton shirt'")
    category: Optional[str] = Field(None, description="Category name, e.g. 'Shirts'")
    color: Optional[str] = Field(None, description="Single color, e.g. 'black'")
    size: Optional[str] = Field(None, description="Size, e.g. 'M', 'L', '42'")
    min_price: Optional[float] = Field(None, description="Minimum price in PKR")
    max_price: Optional[float] = Field(None, description="Maximum price in PKR")
    store: Optional[str] = Field(None, description="Store name to restrict to")
    in_stock_only: bool = Field(False, description="Only products currently in stock")


class get_product_details(BaseModel):
    """Get full details (description, all colors and sizes, stock, store) of one product by its id."""
    product_id: int


class check_inventory(BaseModel):
    """Check whether a product (optionally a specific color/size/quantity) is available right now."""
    product_id: int
    color: Optional[str] = None
    size: Optional[str] = None
    quantity: int = Field(1, ge=1, le=100)


class search_stores(BaseModel):
    """Find seller stores on OneSeller by name or description."""
    query: str = Field(..., description="Store name or keyword")


class compare_products(BaseModel):
    """Compare 2-5 products side by side (price, stock, colors, sizes) using live data."""
    product_ids: list[int] = Field(..., min_length=2, max_length=5)


class save_preference(BaseModel):
    """Save a shopping preference the customer explicitly stated, so it can be used in future conversations."""
    key: Literal["category", "color", "size", "budget_max", "note"]
    value: str = Field(..., max_length=120)


class add_to_cart(BaseModel):
    """Add a product to the customer's cart. Use the product id from search results."""
    product_id: int
    quantity: int = Field(1, ge=1, le=100)
    color: Optional[str] = None
    size: Optional[str] = None


class remove_from_cart(BaseModel):
    """Remove a product from the customer's cart."""
    product_id: int


class get_cart(BaseModel):
    """Show the customer's current cart with totals."""


class set_delivery_details(BaseModel):
    """Record delivery details the customer provided for this order (only values they actually gave)."""
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None


class prepare_checkout(BaseModel):
    """Validate the cart and delivery details and produce an order summary that the customer must confirm.
    Call this when the customer wants to check out / place an order. It does NOT place the order."""


class create_order(BaseModel):
    """Place the order. Only valid right after the customer explicitly confirmed the checkout summary."""
    confirmation_token: str


class get_my_orders(BaseModel):
    """List the customer's own recent orders and their status."""


AGENT_TOOLS: dict[str, list[type[BaseModel]]] = {
    "catalog_agent": [search_products, get_product_details, check_inventory, search_stores],
    "sales_agent": [search_products, get_product_details, compare_products, save_preference],
    "order_agent": [add_to_cart, remove_from_cart, get_cart, set_delivery_details, prepare_checkout,
                    create_order, get_my_orders],
}
SCHEMAS: dict[str, type[BaseModel]] = {cls.__name__: cls for tools in AGENT_TOOLS.values() for cls in tools}


# ------------------------------------------------------------------ helpers

def compact(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "price": catalog.money(p.price), "category": p.category,
            "colors": catalog.decode_list(p.colors),
            "sizes": [catalog.display_size(s) for s in catalog.decode_list(p.sizes)],
            "stock": p.stock, "store": p.store.name}


def _cart_summary(db: Session, principal: str) -> dict:
    out = cart_svc.cart_out(cart_svc.get_or_create_cart(db, principal))
    return {"items": [{k: i[k] for k in ("product_id", "name", "unit_price", "quantity", "color", "size",
                                          "subtotal", "available")} | {"store": i["store"]["name"]}
                      for i in out["items"]],
            "total": out["total"], "item_count": out["item_count"], "currency": out["currency"],
            "issues": out["issues"]}


# ------------------------------------------------------------------ implementations

def _search_products(db: Session, ctx: ToolContext, a: search_products) -> dict:
    rows, total = catalog.search_products(
        db, query=a.query, category=a.category, color=a.color, size=a.size, min_price=a.min_price,
        max_price=a.max_price, store=a.store, in_stock_only=a.in_stock_only, limit=8, parse_query=True)
    if not rows and a.category and a.query:  # LLMs often over-constrain: retry with keywords only
        rows, total = catalog.search_products(
            db, query=f"{a.query} {a.category}", color=a.color, size=a.size, min_price=a.min_price,
            max_price=a.max_price, store=a.store, in_stock_only=a.in_stock_only, limit=8, parse_query=True)
    items = [compact(p) for p in rows]
    ctx.updates["last_products"] = items
    return {"ok": True, "count": len(items), "total_matches": total, "products": items,
            "note": "No products match these filters." if not items else None}


def _get_product_details(db: Session, ctx: ToolContext, a: get_product_details) -> dict:
    p = catalog.get_visible_product(db, a.product_id)
    d = compact(p) | {"description": (p.description or "")[:400], "in_stock": p.stock > 0,
                      "store_slug": p.store.slug}
    _merge_last(ctx, [compact(p)])
    return {"ok": True, "product": d}


def _check_inventory(db: Session, ctx: ToolContext, a: check_inventory) -> dict:
    p = catalog.get_visible_product(db, a.product_id)
    colors, sizes = catalog.decode_list(p.colors), catalog.decode_list(p.sizes)
    color_ok = not a.color or not colors or catalog.norm_color(a.color) in colors
    size_ok = not a.size or not sizes or catalog.norm_size(a.size) in sizes
    available = p.stock >= a.quantity and color_ok and size_ok
    _merge_last(ctx, [compact(p)])
    return {"ok": True, "product_id": p.id, "name": p.name, "stock": p.stock, "requested_quantity": a.quantity,
            "color_available": color_ok, "size_available": size_ok, "available": available,
            "colors": colors, "sizes": [catalog.display_size(s) for s in sizes], "price": catalog.money(p.price)}


def _search_stores(db: Session, ctx: ToolContext, a: search_stores) -> dict:
    from ..routers.marketplace import store_search  # shared implementation
    stores = store_search(db, a.query, limit=6)
    return {"ok": True, "count": len(stores),
            "stores": [{k: s[k] for k in ("name", "slug", "tagline", "product_count", "premium")} for s in stores]}


def _compare_products(db: Session, ctx: ToolContext, a: compare_products) -> dict:
    rows = []
    for pid in dict.fromkeys(a.product_ids):
        try:
            rows.append(compact(catalog.get_visible_product(db, pid)))
        except AppError:
            rows.append({"id": pid, "error": "not found or unavailable"})
    valid = [r for r in rows if "error" not in r]
    if len(valid) < 2:
        return {"ok": False, "error": "Need at least two available products to compare", "products": rows}
    cheapest = min(valid, key=lambda r: r["price"])
    priciest = max(valid, key=lambda r: r["price"])
    _merge_last(ctx, valid, replace=True)
    return {"ok": True, "products": rows, "cheapest_id": cheapest["id"], "most_expensive_id": priciest["id"],
            "price_difference": round(priciest["price"] - cheapest["price"], 2),
            "most_in_stock_id": max(valid, key=lambda r: r["stock"])["id"]}


def _save_preference(db: Session, ctx: ToolContext, a: save_preference) -> dict:
    key = {"category": "preferred_categories", "color": "preferred_colors", "size": "preferred_sizes",
           "budget_max": "budget_max", "note": "notes"}[a.key]
    value = a.value.strip()
    if a.key == "color":
        value = catalog.norm_color(value)
    elif a.key == "size":
        value = catalog.display_size(catalog.norm_size(value))
    elif a.key == "budget_max":
        digits = "".join(ch for ch in value if ch.isdigit() or ch == ".")
        if not digits:
            return {"ok": False, "error": "budget_max must be a number"}
        value = str(int(float(digits)))
    if guard.screen(value):
        return {"ok": False, "error": "Preference rejected"}
    profile = memory.remember(db, ctx.principal, key, value)
    ctx.updates["profile"] = profile
    return {"ok": True, "saved": {a.key: value}}


def _add_to_cart(db: Session, ctx: ToolContext, a: add_to_cart) -> dict:
    cart_svc.add_item(db, ctx.principal, a.product_id, a.quantity, a.color, a.size)
    ctx.updates["pending_order"] = None  # cart changed → any earlier confirmation is void
    return {"ok": True, "added": {"product_id": a.product_id, "quantity": a.quantity, "color": a.color,
                                  "size": a.size}, "cart": _cart_summary(db, ctx.principal)}


def _remove_from_cart(db: Session, ctx: ToolContext, a: remove_from_cart) -> dict:
    cart_svc.remove_item(db, ctx.principal, product_id=a.product_id)
    ctx.updates["pending_order"] = None
    return {"ok": True, "removed_product_id": a.product_id, "cart": _cart_summary(db, ctx.principal)}


def _get_cart(db: Session, ctx: ToolContext, a: get_cart) -> dict:
    return {"ok": True, "cart": _cart_summary(db, ctx.principal)}


def _set_delivery_details(db: Session, ctx: ToolContext, a: set_delivery_details) -> dict:
    delivery = dict(ctx.state.get("delivery") or {})
    for k, v in a.model_dump().items():
        if v and str(v).strip():
            delivery[k] = str(v).strip()[:300]
    ctx.updates["delivery"] = delivery
    ctx.updates["pending_order"] = None
    missing = order_svc.missing_delivery_fields(delivery)
    return {"ok": True, "delivery": delivery, "missing": missing}


def _prepare_checkout(db: Session, ctx: ToolContext, a: prepare_checkout) -> dict:
    cart = cart_svc.get_or_create_cart(db, ctx.principal)
    summary = _cart_summary(db, ctx.principal)
    if not cart.items:
        return {"ok": False, "status": "empty_cart", "error": "The cart is empty."}
    if summary["issues"]:
        return {"ok": False, "status": "cart_issues", "issues": summary["issues"]}
    delivery = dict(ctx.state.get("delivery") or {})
    missing = order_svc.missing_delivery_fields(delivery)
    if missing:
        return {"ok": True, "status": "needs_details", "missing": missing, "cart": summary}
    token = secrets.token_hex(4)
    ctx.updates["pending_order"] = {"token": token, "cart_hash": cart_svc.cart_hash(cart),
                                    "total": summary["total"], "delivery": delivery}
    return {"ok": True, "status": "awaiting_confirmation", "confirmation_token": token, "cart": summary,
            "delivery": delivery, "sandbox": ctx.sandbox}


def _create_order(db: Session, ctx: ToolContext, a: create_order) -> dict:
    """Human-in-the-loop gate, enforced in code (not by the prompt)."""
    pending = ctx.state.get("pending_order")
    if not pending:
        return {"ok": False, "error": "confirmation_required",
                "message": "No confirmed checkout. Call prepare_checkout and ask the customer to confirm first."}
    if a.confirmation_token != pending.get("token"):
        return {"ok": False, "error": "invalid_token", "message": "Confirmation token does not match."}
    if not guard.is_affirmative(ctx.user_message):
        return {"ok": False, "error": "confirmation_required",
                "message": "The customer has not explicitly confirmed. Ask them to reply 'yes' to confirm."}
    cart = cart_svc.get_or_create_cart(db, ctx.principal)
    if cart_svc.cart_hash(cart) != pending.get("cart_hash"):
        ctx.updates["pending_order"] = None
        return {"ok": False, "error": "cart_changed", "message": "The cart changed since the summary. Re-run checkout."}
    key = hashlib.sha256(f"{ctx.principal}|{pending['token']}".encode()).hexdigest()[:32]
    created = order_svc.checkout(db, ctx.principal, pending["delivery"], idempotency_key=key,
                                 channel=ctx.channel, customer_id=ctx.customer_id, sandbox=ctx.sandbox)
    ctx.updates["pending_order"] = None
    return {"ok": True, "orders": [{"order_id": o.id, "store": o.store.name, "total": catalog.money(o.total),
                                    "status": o.status.value,
                                    "items": [f"{i.quantity} x {i.product_name}" for i in o.items]}
                                   for o in created],
            "grand_total": round(sum(catalog.money(o.total) for o in created), 2), "sandbox": ctx.sandbox}


def _get_my_orders(db: Session, ctx: ToolContext, a: get_my_orders) -> dict:
    rows = order_svc.list_customer_orders(db, ctx.principal)[:5]
    return {"ok": True, "orders": [{"order_id": o.id, "store": o.store.name, "status": o.status.value,
                                    "total": catalog.money(o.total),
                                    "created_at": catalog.as_utc(o.created_at).date().isoformat(),
                                    "items": [f"{i.quantity} x {i.product_name}" for i in o.items]} for o in rows]}


def _merge_last(ctx: ToolContext, items: list[dict], replace: bool = False) -> None:
    if replace:
        ctx.updates["last_products"] = items
        return
    current = list(ctx.updates.get("last_products") or ctx.state.get("last_products") or [])
    ids = {i["id"] for i in items}
    ctx.updates["last_products"] = (items + [c for c in current if c["id"] not in ids])[:10]


IMPLS: dict[str, Callable[[Session, ToolContext, Any], dict]] = {
    "search_products": _search_products, "get_product_details": _get_product_details,
    "check_inventory": _check_inventory, "search_stores": _search_stores, "compare_products": _compare_products,
    "save_preference": _save_preference, "add_to_cart": _add_to_cart, "remove_from_cart": _remove_from_cart,
    "get_cart": _get_cart, "set_delivery_details": _set_delivery_details, "prepare_checkout": _prepare_checkout,
    "create_order": _create_order, "get_my_orders": _get_my_orders,
}


def execute(name: str, args: dict, agent: str, ctx: ToolContext) -> dict:
    """Validated execution: tool must belong to the active agent, args must pass the schema."""
    allowed = {cls.__name__ for cls in AGENT_TOOLS.get(agent, [])}
    if name not in allowed:
        return {"ok": False, "error": "tool_not_allowed", "message": f"{name} is not available to {agent}."}
    schema = SCHEMAS[name]
    try:
        parsed = schema.model_validate(args or {})
    except ValidationError as exc:
        return {"ok": False, "error": "invalid_arguments",
                "details": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:5]}
    db = SessionLocal()
    try:
        return IMPLS[name](db, ctx, parsed)
    except AppError as exc:
        db.rollback()
        return {"ok": False, "error": exc.code, "message": exc.message}
    except Exception as exc:  # never let a tool crash the graph
        db.rollback()
        import logging
        logging.getLogger("oneseller.tools").exception("tool %s failed", name)
        return {"ok": False, "error": "tool_failed", "message": "Internal error while running the tool."}
    finally:
        db.close()


def delivery_from_profile(principal: str) -> dict:
    """Authenticated customers: prefill delivery details from their saved profile."""
    if not principal.startswith("user:"):
        return {}
    with SessionLocal() as db:
        u = db.get(User, int(principal.split(":", 1)[1]))
        if not u:
            return {}
        d = {"customer_name": u.full_name, "phone": u.phone, "address": u.address, "city": u.city}
        return {k: v for k, v in d.items() if v}


def dump(result: dict) -> str:
    return "<tool_data>" + json.dumps({k: v for k, v in result.items() if v is not None}, default=str) + "</tool_data>"
