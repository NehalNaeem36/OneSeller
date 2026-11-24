"""Agent tools.

Each tool = a Pydantic argument model (its class name is the tool name, its docstring the description; this
is what the LLM sees) + a DB-backed implementation. Implementations receive a `ToolContext` built by the
server from graph config — identity is never an LLM-controllable argument.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field, ValidationError
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

def _coerce_id(v: Any) -> Any:
    """Models often write ids as "#27" or "27"; accept those, leave anything else to normal validation."""
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(?:#|id[:\s]*)?\s*(\d+)\s*", v, re.I)
        if m:
            return int(m.group(1))
    return v


ProductId = Annotated[int, BeforeValidator(_coerce_id)]


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
    """Get full details (description, colors, sizes, stock, store) of one product, by id or by name."""
    product_id: Optional[ProductId] = Field(None, description="Product id from earlier results, if known")
    product_name: Optional[str] = Field(None, description="Product name if the id is not known, e.g. 'Teal Printed Kurta'")


class check_inventory(BaseModel):
    """Check whether a product (optionally a specific color/size/quantity) is in stock right now. Pass the product
    id, or the product name if you don't know the id."""
    product_id: Optional[ProductId] = Field(None, description="Product id from earlier results, if known")
    product_name: Optional[str] = Field(None, description="Product name if the id is not known, e.g. 'Teal Printed Kurta'")
    color: Optional[str] = None
    size: Optional[str] = None
    quantity: int = Field(1, ge=1, le=100)


class search_stores(BaseModel):
    """Find seller stores on OneSeller by name or description."""
    query: str = Field(..., description="Store name or keyword")


class compare_products(BaseModel):
    """Compare 2-5 products side by side (price, stock, colors, sizes) using live data. Pass ids if known,
    otherwise product names."""
    product_ids: list[ProductId] = Field(default_factory=list, max_length=5)
    product_names: list[str] = Field(default_factory=list, max_length=5)


class save_preference(BaseModel):
    """Save a shopping preference the customer explicitly stated, so it can be used in future conversations."""
    key: Literal["category", "color", "size", "budget_max", "note"]
    value: str = Field(..., max_length=120)


class add_to_cart(BaseModel):
    """Add a product to the customer's cart. Pass the product id from earlier results, or the product name if the
    customer named a product you haven't looked up (it is resolved against the live catalog)."""
    product_id: Optional[ProductId] = Field(None, description="Product id from earlier results, if known")
    product_name: Optional[str] = Field(None, description="Product name if the id is not known, e.g. 'Teal Printed Kurta'")
    quantity: int = Field(1, ge=1, le=100)
    color: Optional[str] = None
    size: Optional[str] = None


class remove_from_cart(BaseModel):
    """Remove a product from the customer's cart, by product id or by (part of) its name, e.g. 't-shirt'."""
    product_id: Optional[ProductId] = Field(None, description="Product id from earlier results, if known")
    product_name: Optional[str] = Field(None, description="Product name if the id is not known, e.g. 'Teal Printed Kurta'")


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


def resolve_product(db: Session, ctx: ToolContext, product_id: int | None, product_name: str | None) -> Product:
    """Server-side product resolution: id, else exact name, else recently shown products, else catalog search.
    Ambiguous names raise an error listing candidates instead of guessing."""
    if product_id:
        return catalog.get_visible_product(db, product_id)
    name = (product_name or "").strip()
    if not name:
        raise AppError(400, "missing_product", "Provide a product_id or product_name.")
    norm = catalog._norm_text(name)
    for row in ctx.updates.get("last_products") or ctx.state.get("last_products") or []:
        if catalog._norm_text(row["name"]) == norm:
            return catalog.get_visible_product(db, row["id"])
    rows, _ = catalog.search_products(db, query=name, limit=10, parse_query=True)
    exact = [p for p in rows if catalog._norm_text(p.name) == norm]
    if exact:
        return exact[0]
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise AppError(404, "not_found", f"No product named '{name}' was found in the catalog.")
    tokens = set(catalog.keyword_tokens(name))
    best = [p for p in rows if tokens and tokens <= set(catalog.keyword_tokens(p.name))]
    if len(best) == 1:
        return best[0]
    ctx.updates["last_products"] = [compact(p) for p in rows[:6]]
    raise AppError(409, "ambiguous_product", f"'{name}' matches several products: "
                   + "; ".join(f"#{p.id} {p.name} (Rs. {catalog.money(p.price):,.0f})" for p in rows[:6])
                   + ". Ask the customer which one.")


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
    p = resolve_product(db, ctx, a.product_id, a.product_name)
    d = compact(p) | {"description": (p.description or "")[:400], "in_stock": p.stock > 0,
                      "store_slug": p.store.slug}
    _merge_last(ctx, [compact(p)])
    return {"ok": True, "product": d}


def _check_inventory(db: Session, ctx: ToolContext, a: check_inventory) -> dict:
    p = resolve_product(db, ctx, a.product_id, a.product_name)
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
    refs = [(pid, None) for pid in dict.fromkeys(a.product_ids)] + [(None, n) for n in a.product_names]
    for pid, name in refs:
        try:
            row = compact(resolve_product(db, ctx, pid, name))
            if all(r.get("id") != row["id"] for r in rows):
                rows.append(row)
        except AppError as exc:
            rows.append({"id": pid, "name": name, "error": exc.message})
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


ADD_INTENT_RE = re.compile(r"\b(add|cart|basket|buy|take|want|get me|order|purchase|include|another|more|"
                           r"one more|i'?ll have|grab)\b|\b\d+\s*x\b", re.I)


def _add_to_cart(db: Session, ctx: ToolContext, a: add_to_cart) -> dict:
    if ctx.user_message and not ADD_INTENT_RE.search(ctx.user_message):
        return {"ok": False, "error": "not_requested",
                "message": "The customer did not ask to add an item in this message. The cart is unchanged.",
                "cart": _cart_summary(db, ctx.principal)}
    p = resolve_product(db, ctx, a.product_id, a.product_name)
    cart_svc.add_item(db, ctx.principal, p.id, a.quantity, a.color, a.size)
    ctx.updates["pending_order"] = None  # cart changed → any earlier confirmation is void
    return {"ok": True, "added": {"product_id": p.id, "name": p.name, "quantity": a.quantity, "color": a.color,
                                  "size": a.size}, "cart": _cart_summary(db, ctx.principal)}


def _remove_from_cart(db: Session, ctx: ToolContext, a: remove_from_cart) -> dict:
    pid = a.product_id
    if not pid:
        cart = cart_svc.get_or_create_cart(db, ctx.principal)
        want = set(catalog.keyword_tokens(a.product_name or ""))
        matches = [i for i in cart.items
                   if want and want <= set(catalog.keyword_tokens(f"{i.product.name} {i.product.category}"))]
        if len(cart.items) == 1 and not matches and not want:
            matches = list(cart.items)
        if not matches:
            return {"ok": False, "error": "not_in_cart", "message": f"'{a.product_name}' is not in the cart.",
                    "cart": _cart_summary(db, ctx.principal)}
        if len({i.product_id for i in matches}) > 1:
            return {"ok": False, "error": "ambiguous", "message": "Several cart items match: "
                    + ", ".join(i.product.name for i in matches)}
        pid = matches[0].product_id
    cart_svc.remove_item(db, ctx.principal, product_id=pid)
    ctx.updates["pending_order"] = None
    return {"ok": True, "removed_product_id": pid, "cart": _cart_summary(db, ctx.principal)}


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
