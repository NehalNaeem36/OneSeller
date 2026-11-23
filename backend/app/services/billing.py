"""Plans, free trial, mock payments and backend-enforced entitlements."""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import AppError
from ..models import BillingPayment, Order, OrderStatus, Plan, Store, Subscription
from .catalog import as_utc, now_utc


def plan_catalog() -> dict:
    s = get_settings()
    return {
        "trial": {"name": "Free trial", "price": 0, "order_limit": s.trial_order_limit,
                  "features": ["Storefront", "AI sales agent", "Product management"]},
        "standard": {"name": "Standard", "price": s.standard_price, "order_limit": s.standard_order_limit,
                     "features": ["Everything in trial", f"{s.standard_order_limit} orders / month"]},
        "premium": {"name": "Premium", "price": s.premium_price, "order_limit": s.premium_order_limit,
                    "features": ["Everything in Standard", f"{s.premium_order_limit} orders / month",
                                 "Premium badge", "Featured marketplace placement"]},
    }


def start_trial(db: Session, store: Store) -> Subscription:
    start = now_utc()
    sub = Subscription(store_id=store.id, plan=Plan.trial, period_start=start,
                       period_end=start + relativedelta(months=1))
    db.add(sub)
    return sub


def get_subscription(db: Session, store: Store) -> Subscription:
    sub = db.scalars(select(Subscription).where(Subscription.store_id == store.id)).first()
    if not sub:  # self-heal legacy rows
        sub = start_trial(db, store)
        db.commit()
    return sub


def is_active(sub: Subscription) -> bool:
    return as_utc(sub.period_end) > now_utc() and not sub.cancelled


def orders_this_period(db: Session, store: Store, sub: Subscription) -> int:
    since = max(as_utc(sub.period_start), now_utc() - timedelta(days=31))
    return db.scalar(
        select(func.count(Order.id)).where(Order.store_id == store.id, Order.created_at >= since,
                                           Order.status != OrderStatus.cancelled,
                                           Order.is_sandbox.is_(False))
    ) or 0


def status(db: Session, store: Store) -> dict:
    sub = get_subscription(db, store)
    plans = plan_catalog()
    active = is_active(sub)
    end = as_utc(sub.period_end)
    remaining = max(0, (end - now_utc()).days) if active else 0
    used = orders_this_period(db, store, sub)
    return {
        "plan": sub.plan.value,
        "plan_name": plans[sub.plan.value]["name"],
        "status": "active" if active else "expired",
        "is_trial": sub.plan == Plan.trial,
        "period_start": as_utc(sub.period_start).isoformat(),
        "period_end": end.isoformat(),
        "days_remaining": remaining,
        "order_limit": plans[sub.plan.value]["order_limit"],
        "orders_used": used,
        "plans": plans,
        "simulation_enabled": get_settings().allow_billing_simulation,
    }


def assert_store_active(db: Session, store: Store) -> None:
    sub = get_subscription(db, store)
    if not is_active(sub):
        what = "free trial" if sub.plan == Plan.trial else "subscription"
        raise AppError(402, "subscription_expired",
                       f"Your {what} has expired. Renew or upgrade your plan in Billing to continue.")


def assert_can_accept_order(db: Session, store: Store, sandbox: bool = False) -> None:
    sub = get_subscription(db, store)
    if not is_active(sub):
        raise AppError(409, "store_unavailable", f"{store.name} is not accepting orders right now.")
    if sandbox:
        return
    limit = plan_catalog()[sub.plan.value]["order_limit"]
    if orders_this_period(db, store, sub) >= limit:
        raise AppError(409, "store_order_limit",
                       f"{store.name} has reached its monthly order limit. Please try again later.")


def pay(db: Session, store: Store, plan: str) -> dict:
    """Mock payment: records a payment, then activates / renews / upgrades the plan."""
    s = get_settings()
    target = Plan(plan)
    price = s.standard_price if target == Plan.standard else s.premium_price
    sub = get_subscription(db, store)
    now = now_utc()
    renewing_same = is_active(sub) and sub.plan == target
    start = as_utc(sub.period_end) if renewing_same else now
    if not renewing_same:
        sub.period_start = now
    sub.plan = target
    sub.cancelled = False
    sub.period_end = start + relativedelta(months=1)
    payment = BillingPayment(store_id=store.id, plan=target, amount=Decimal(str(price)),
                             currency=s.currency, reference=f"MOCK-{uuid.uuid4().hex[:16].upper()}")
    db.add(payment)
    db.commit()
    return {"payment_reference": payment.reference, "amount": float(price), "currency": s.currency,
            "action": "renewed" if renewing_same else "activated", **status(db, store)}


def simulate_expiry(db: Session, store: Store) -> dict:
    if not get_settings().allow_billing_simulation:
        raise AppError(403, "forbidden", "Billing simulation is disabled")
    sub = get_subscription(db, store)
    sub.period_end = now_utc() - timedelta(minutes=1)
    db.commit()
    return status(db, store)


def payments(db: Session, store: Store) -> list[dict]:
    rows = db.scalars(select(BillingPayment).where(BillingPayment.store_id == store.id)
                      .order_by(BillingPayment.id.desc()).limit(50))
    return [{"reference": p.reference, "plan": p.plan.value, "amount": float(p.amount),
             "currency": p.currency, "created_at": as_utc(p.created_at).isoformat()} for p in rows]
