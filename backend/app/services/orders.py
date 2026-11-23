"""Transactional checkout and order lifecycle."""
from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..errors import AppError, bad_request, not_found
from ..models import Order, OrderItem, OrderStatus, Product, Store
from . import billing, cart as cart_svc, catalog

REQUIRED_DELIVERY = ("customer_name", "phone", "address", "city")

ALLOWED_TRANSITIONS = {
    OrderStatus.confirmed: {OrderStatus.processing, OrderStatus.shipped, OrderStatus.cancelled},
    OrderStatus.processing: {OrderStatus.shipped, OrderStatus.cancelled},
    OrderStatus.shipped: {OrderStatus.delivered},
    OrderStatus.delivered: set(),
    OrderStatus.cancelled: set(),
}


def missing_delivery_fields(delivery: dict) -> list[str]:
    return [f for f in REQUIRED_DELIVERY if not str(delivery.get(f) or "").strip()]


def checkout(db: Session, principal: str, delivery: dict, *, idempotency_key: str, channel: str = "web",
             customer_id: int | None = None, sandbox: bool = False) -> list[Order]:
    """Create one order per store from the principal's cart in a single transaction.

    Stock is decremented with a conditional UPDATE (stock >= qty) so concurrent checkouts can't oversell.
    Replaying the same idempotency key returns the original orders instead of creating duplicates.
    """
    clean = re.sub(r"[^A-Za-z0-9\-]", "", idempotency_key or "")[:80]
    if len(clean) < 8:
        raise bad_request("A valid idempotency key is required", code="invalid_idempotency_key")
    idempotency_key = hashlib.sha256(f"{principal}|{clean}".encode()).hexdigest()[:40]
    existing = db.scalars(select(Order).where(Order.idempotency_key.like(f"{idempotency_key}:%"),
                                              Order.principal == principal)
                          .options(joinedload(Order.items), joinedload(Order.store))).unique().all()
    if existing:
        return list(existing)

    missing = missing_delivery_fields(delivery)
    if missing:
        raise bad_request(f"Missing delivery details: {', '.join(missing)}", code="missing_delivery",
                          missing=missing)

    cart = cart_svc.get_or_create_cart(db, principal)
    if not cart.items:
        raise bad_request("Your cart is empty", code="empty_cart")

    affect_inventory = not sandbox or get_settings().public_api_orders_affect_inventory
    by_store: dict[int, list] = defaultdict(list)
    for line in cart.items:
        by_store[line.product.store_id].append(line)

    group = uuid.uuid4().hex[:16]
    created: list[Order] = []
    try:
        for store_id, lines in by_store.items():
            store = db.get(Store, store_id)
            billing.assert_can_accept_order(db, store, sandbox=sandbox)
            order = Order(principal=principal, customer_id=customer_id, store_id=store_id,
                          status=OrderStatus.confirmed, total=Decimal("0"), currency=get_settings().currency,
                          customer_name=delivery["customer_name"].strip(), phone=delivery["phone"].strip(),
                          address=delivery["address"].strip(), city=delivery["city"].strip(),
                          postal_code=(delivery.get("postal_code") or None), payment_status="mock_paid",
                          channel=channel, is_sandbox=sandbox,
                          idempotency_key=f"{idempotency_key}:{store_id}", checkout_group=group)
            total = Decimal("0")
            for line in lines:
                product = line.product
                if not product.is_active:
                    raise AppError(409, "product_unavailable", f"'{product.name}' is no longer available")
                if affect_inventory:
                    res = db.execute(update(Product)
                                     .where(Product.id == product.id, Product.stock >= line.quantity)
                                     .values(stock=Product.stock - line.quantity))
                    if res.rowcount != 1:
                        raise AppError(409, "insufficient_stock",
                                       f"Not enough stock for '{product.name}' (only {product.stock} left)")
                elif product.stock < line.quantity:
                    raise AppError(409, "insufficient_stock",
                                   f"Not enough stock for '{product.name}' (only {product.stock} left)")
                total += product.price * line.quantity
                order.items.append(OrderItem(product_id=product.id, product_name=product.name,
                                             unit_price=product.price, quantity=line.quantity,
                                             color=line.color, size=line.size))
            order.total = total
            db.add(order)
            created.append(order)
        cart.items.clear()
        db.commit()
    except IntegrityError:
        db.rollback()  # concurrent duplicate submit with the same key
        return list(db.scalars(select(Order).where(Order.idempotency_key.like(f"{idempotency_key}:%"),
                                                   Order.principal == principal)).all())
    except Exception:
        db.rollback()
        raise
    for o in created:
        db.refresh(o)
    return created


def order_out(o: Order, *, for_seller: bool = False) -> dict:
    data = {
        "id": o.id, "status": o.status.value, "total": catalog.money(o.total), "currency": o.currency,
        "payment_status": o.payment_status, "channel": o.channel, "is_sandbox": o.is_sandbox,
        "created_at": catalog.as_utc(o.created_at).isoformat(), "checkout_group": o.checkout_group,
        "store": {"id": o.store.id, "name": o.store.name, "slug": o.store.slug} if o.store else None,
        "items": [{"product_id": i.product_id, "name": i.product_name, "unit_price": catalog.money(i.unit_price),
                   "quantity": i.quantity, "color": i.color or None,
                   "size": catalog.display_size(i.size) if i.size else None,
                   "subtotal": catalog.money(i.unit_price * i.quantity)} for i in o.items],
        "delivery": {"customer_name": o.customer_name, "phone": o.phone, "address": o.address,
                     "city": o.city, "postal_code": o.postal_code},
    }
    return data


def list_customer_orders(db: Session, principal: str) -> list[Order]:
    return list(db.scalars(select(Order).where(Order.principal == principal)
                           .options(joinedload(Order.items), joinedload(Order.store))
                           .order_by(Order.id.desc())).unique())


def get_customer_order(db: Session, principal: str, order_id: int) -> Order:
    o = db.scalars(select(Order).where(Order.id == order_id, Order.principal == principal)
                   .options(joinedload(Order.items), joinedload(Order.store))).first()
    if not o:
        raise not_found("Order")
    return o


def get_store_order(db: Session, store: Store, order_id: int) -> Order:
    o = db.scalars(select(Order).where(Order.id == order_id, Order.store_id == store.id)
                   .options(joinedload(Order.items), joinedload(Order.store))).first()
    if not o:
        raise not_found("Order")
    return o


def set_status(db: Session, store: Store, order_id: int, new_status: str) -> Order:
    o = get_store_order(db, store, order_id)
    target = OrderStatus(new_status)
    if target not in ALLOWED_TRANSITIONS[o.status]:
        raise bad_request(f"Cannot change status from {o.status.value} to {target.value}",
                          code="invalid_transition")
    if target == OrderStatus.cancelled and not o.is_sandbox:
        for item in o.items:  # return stock
            if item.product_id:
                db.execute(update(Product).where(Product.id == item.product_id)
                           .values(stock=Product.stock + item.quantity))
    o.status = target
    db.commit()
    db.refresh(o)
    return o
