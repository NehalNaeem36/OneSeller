"""Carts keyed by principal (user:<id> for authenticated customers, api:<id> for the public API)."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..errors import AppError, bad_request, not_found
from ..models import Cart, CartItem, Product, Store
from . import catalog


def get_or_create_cart(db: Session, principal: str) -> Cart:
    cart = db.scalars(select(Cart).where(Cart.principal == principal)
                      .options(joinedload(Cart.items).joinedload(CartItem.product)
                               .joinedload(Product.store).joinedload(Store.subscription))).first()
    if not cart:
        cart = Cart(principal=principal)
        db.add(cart)
        db.flush()
    return cart


def _resolve_variant(product: Product, color: str | None, size: str | None) -> tuple[str, str]:
    colors = catalog.decode_list(product.colors)
    sizes = catalog.decode_list(product.sizes)
    c = catalog.norm_color(color) if color else ""
    z = catalog.norm_size(size) if size else ""
    if c and colors and c not in colors:
        raise bad_request(f"'{product.name}' is not available in {color}. Available colors: "
                          f"{', '.join(colors)}", code="invalid_variant")
    if z and sizes and z not in sizes:
        raise bad_request(f"'{product.name}' is not available in size {size}. Available sizes: "
                          f"{', '.join(catalog.display_size(s) for s in sizes)}", code="invalid_variant")
    if not c and len(colors) == 1:
        c = colors[0]
    if not z and len(sizes) == 1:
        z = sizes[0]
    return c, z


def add_item(db: Session, principal: str, product_id: int, quantity: int = 1,
             color: str | None = None, size: str | None = None) -> Cart:
    if quantity < 1 or quantity > 100:
        raise bad_request("Quantity must be between 1 and 100", code="invalid_quantity")
    product = catalog.get_visible_product(db, product_id)
    c, z = _resolve_variant(product, color, size)
    cart = get_or_create_cart(db, principal)
    line = next((i for i in cart.items if i.product_id == product.id and i.color == c and i.size == z), None)
    new_qty = quantity + (line.quantity if line else 0)
    if product.stock <= 0:
        raise AppError(409, "out_of_stock", f"'{product.name}' is out of stock")
    if new_qty > product.stock:
        raise AppError(409, "insufficient_stock",
                       f"Only {product.stock} unit(s) of '{product.name}' are available")
    if line:
        line.quantity = new_qty
    else:
        cart.items.append(CartItem(product_id=product.id, quantity=quantity, color=c, size=z))
    db.commit()
    return get_or_create_cart(db, principal)


def update_item(db: Session, principal: str, item_id: int, quantity: int) -> Cart:
    cart = get_or_create_cart(db, principal)
    line = next((i for i in cart.items if i.id == item_id), None)
    if not line:
        raise not_found("Cart item")
    if quantity > line.product.stock:
        raise AppError(409, "insufficient_stock", f"Only {line.product.stock} unit(s) available")
    line.quantity = quantity
    db.commit()
    return get_or_create_cart(db, principal)


def remove_item(db: Session, principal: str, item_id: int | None = None, product_id: int | None = None) -> Cart:
    cart = get_or_create_cart(db, principal)
    lines = [i for i in cart.items if (item_id and i.id == item_id) or (product_id and i.product_id == product_id)]
    if not lines:
        raise not_found("Cart item")
    for line in lines:
        cart.items.remove(line)
    db.commit()
    return get_or_create_cart(db, principal)


def clear(db: Session, principal: str) -> None:
    cart = get_or_create_cart(db, principal)
    cart.items.clear()


def cart_out(cart: Cart) -> dict:
    lines, total, issues = [], 0.0, []
    for i in cart.items:
        p = i.product
        price = catalog.money(p.price)
        sub = price * i.quantity
        available = p.is_active and p.stock >= i.quantity
        if not available:
            issues.append(f"{p.name}: " + ("no longer available" if not p.is_active else f"only {p.stock} left"))
        total += sub
        lines.append({"item_id": i.id, "product_id": p.id, "name": p.name, "unit_price": price,
                      "quantity": i.quantity, "color": i.color or None,
                      "size": catalog.display_size(i.size) if i.size else None, "subtotal": round(sub, 2),
                      "stock": p.stock, "available": available, "image_url": catalog.image_url(p.image_id),
                      "store": {"id": p.store.id, "name": p.store.name, "slug": p.store.slug}})
    return {"items": lines, "total": round(total, 2), "item_count": sum(i.quantity for i in cart.items),
            "currency": catalog.get_settings().currency, "issues": issues}


def cart_hash(cart: Cart) -> str:
    sig = sorted((i.product_id, i.quantity, i.color, i.size, str(i.product.price)) for i in cart.items)
    return hashlib.sha256(json.dumps(sig).encode()).hexdigest()[:24]
