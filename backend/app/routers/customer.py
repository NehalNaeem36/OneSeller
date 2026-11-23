from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import bad_request
from ..models import User
from ..schemas import CartItemIn, CartItemUpdate, CheckoutIn, ProfileIn, UserOut
from ..security import customer_principal, require_customer
from ..services import cart as cart_svc, memory, orders as order_svc

router = APIRouter(prefix="/api", tags=["customer"])


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(require_customer)):
    return user


@router.put("/me", response_model=UserOut)
def update_me(body: ProfileIn, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(user, k, (v.strip() if isinstance(v, str) else v) or None)
    if not user.full_name:
        raise bad_request("Name cannot be empty")
    db.add(user)
    db.commit()
    return user


@router.get("/cart")
def get_cart(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    cart = cart_svc.get_or_create_cart(db, customer_principal(user))
    db.commit()
    return cart_svc.cart_out(cart)


@router.post("/cart/items")
def add_cart_item(body: CartItemIn, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cart_svc.cart_out(cart_svc.add_item(db, customer_principal(user), body.product_id, body.quantity,
                                               body.color, body.size))


@router.patch("/cart/items/{item_id}")
def update_cart_item(item_id: int, body: CartItemUpdate, user: User = Depends(require_customer),
                     db: Session = Depends(get_db)):
    return cart_svc.cart_out(cart_svc.update_item(db, customer_principal(user), item_id, body.quantity))


@router.delete("/cart/items/{item_id}")
def delete_cart_item(item_id: int, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return cart_svc.cart_out(cart_svc.remove_item(db, customer_principal(user), item_id=item_id))


@router.post("/checkout")
def checkout(body: CheckoutIn, idempotency_key: str = Header(..., alias="Idempotency-Key"),
             user: User = Depends(require_customer), db: Session = Depends(get_db)):
    if not body.confirm:
        raise bad_request("Please review and explicitly confirm your order", code="confirmation_required")
    delivery = body.delivery.model_dump()
    created = order_svc.checkout(db, customer_principal(user), delivery, idempotency_key=idempotency_key,
                                 channel="web", customer_id=user.id)
    if body.save_details:
        user.phone, user.address, user.city = delivery["phone"], delivery["address"], delivery["city"]
        user.postal_code = delivery.get("postal_code") or user.postal_code
        db.commit()
    return {"orders": [order_svc.order_out(o) for o in created],
            "grand_total": round(sum(float(o.total) for o in created), 2)}


@router.get("/orders")
def my_orders(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return [order_svc.order_out(o) for o in order_svc.list_customer_orders(db, customer_principal(user))]


@router.get("/orders/{order_id}")
def my_order(order_id: int, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return order_svc.order_out(order_svc.get_customer_order(db, customer_principal(user), order_id))


@router.get("/me/memory")
def get_memory(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    return memory.load(db, customer_principal(user))


@router.delete("/me/memory")
def delete_memory(key: str | None = None, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    if key and key not in memory.ALLOWED_KEYS:
        raise bad_request("Unknown memory key")
    memory.forget(db, customer_principal(user), key)
    return memory.load(db, customer_principal(user))
