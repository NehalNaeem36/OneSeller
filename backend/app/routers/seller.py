"""Seller dashboard API. Every query is scoped to the store derived from the seller's JWT."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..db import get_db
from ..errors import AppError, bad_request
from ..models import Order, OrderStatus, Product, ProductImage, Store
from ..schemas import BulkAction, OrderStatusUpdate, PayIn, ProductIn, ProductUpdate, StoreUpdate
from ..security import current_store
from ..services import billing, catalog, orders as order_svc

router = APIRouter(prefix="/api/seller", tags=["seller"])
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.get("/dashboard")
def dashboard(store: Store = Depends(current_store), db: Session = Depends(get_db)):
    s = get_settings()
    real = (Order.store_id == store.id, Order.is_sandbox.is_(False))
    total_sales = db.scalar(select(func.coalesce(func.sum(Order.total), 0))
                            .where(*real, Order.status != OrderStatus.cancelled)) or 0
    counts = dict(db.execute(select(Order.status, func.count(Order.id)).where(*real).group_by(Order.status)).all())
    active_products = db.scalar(select(func.count(Product.id)).where(Product.store_id == store.id,
                                                                     Product.is_active.is_(True))) or 0
    low_stock = list(db.scalars(select(Product).where(Product.store_id == store.id, Product.is_active.is_(True),
                                                      Product.stock <= s.low_stock_threshold)
                                .order_by(Product.stock).limit(10)))
    recent = list(db.scalars(select(Order).where(*real).options(joinedload(Order.items), joinedload(Order.store))
                             .order_by(Order.id.desc()).limit(8)).unique())
    pending = sum(counts.get(st, 0) for st in (OrderStatus.confirmed, OrderStatus.processing, OrderStatus.shipped))
    return {
        "store": {"id": store.id, "name": store.name, "slug": store.slug},
        "kpis": {"total_sales": catalog.money(total_sales), "currency": s.currency,
                 "total_orders": sum(counts.values()), "pending_orders": pending,
                 "completed_orders": counts.get(OrderStatus.delivered, 0),
                 "cancelled_orders": counts.get(OrderStatus.cancelled, 0),
                 "active_products": active_products, "low_stock_products": len(low_stock)},
        "low_stock": [{"id": p.id, "name": p.name, "stock": p.stock} for p in low_stock],
        "recent_orders": [order_svc.order_out(o, for_seller=True) for o in recent],
        "subscription": billing.status(db, store),
    }


# ---------------------------------------------------------------- store customisation

def _store_out(store: Store) -> dict:
    return {"id": store.id, "name": store.name, "slug": store.slug, "tagline": store.tagline,
            "description": store.description, "brand_color": store.brand_color,
            "logo_image_id": store.logo_image_id, "logo_url": catalog.image_url(store.logo_image_id)}


@router.get("/store")
def get_store(store: Store = Depends(current_store)):
    return _store_out(store)


@router.put("/store")
def update_store(body: StoreUpdate, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "logo_image_id" in data and data["logo_image_id"] is not None:
        img = db.get(ProductImage, data["logo_image_id"])
        if not img or img.store_id != store.id:
            raise bad_request("Image not found in your store", code="invalid_image")
    for k, v in data.items():
        setattr(store, k, v)
    db.commit()
    return _store_out(store)


# ---------------------------------------------------------------- products

@router.get("/products")
def list_products(status: str = Query("active", pattern="^(active|deleted|all)$"), q: str | None = None,
                  store: Store = Depends(current_store), db: Session = Depends(get_db)):
    stmt = select(Product).where(Product.store_id == store.id).options(joinedload(Product.store))
    if status == "active":
        stmt = stmt.where(Product.is_active.is_(True))
    elif status == "deleted":
        stmt = stmt.where(Product.is_active.is_(False))
    if q:
        stmt = stmt.where(func.lower(Product.name).like(f"%{q.lower()}%"))
    rows = db.scalars(stmt.order_by(Product.id.desc()).limit(1000)).unique()
    return [catalog.product_out(p, private=True) for p in rows]


@router.post("/products", status_code=201)
def create_product(body: ProductIn, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    billing.assert_store_active(db, store)
    p = catalog.create_product(db, store, body.model_dump())
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise AppError(409, "duplicate_sku", "A product with this SKU already exists in your store")
    db.refresh(p)
    return catalog.product_out(p, private=True)


@router.get("/products/{product_id}")
def get_product(product_id: int, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    return catalog.product_out(catalog.get_owned_product(db, store, product_id), private=True)


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductUpdate, store: Store = Depends(current_store),
                   db: Session = Depends(get_db)):
    billing.assert_store_active(db, store)
    p = catalog.get_owned_product(db, store, product_id)
    catalog.update_product(db, store, p, body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(p)
    return catalog.product_out(p, private=True)


@router.post("/products/{product_id}/restore")
def restore_product(product_id: int, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    p = catalog.get_owned_product(db, store, product_id)
    catalog.restore(p)
    db.commit()
    return catalog.product_out(p, private=True)


@router.delete("/products/{product_id}")
def delete_product(product_id: int, hard: bool = False, confirm: bool = False,
                   store: Store = Depends(current_store), db: Session = Depends(get_db)):
    p = catalog.get_owned_product(db, store, product_id)
    if not hard:
        catalog.soft_delete(p)
        db.commit()
        return {"deleted": "soft", "product_id": product_id, "recoverable": True}
    if not confirm:
        raise bad_request("Permanent deletion requires explicit confirmation (confirm=true)",
                          code="confirmation_required")
    catalog.hard_delete(db, p)
    db.commit()
    return {"deleted": "hard", "product_id": product_id, "recoverable": False}


@router.post("/products/bulk")
def bulk(body: BulkAction, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    if body.action not in ("soft_delete",):
        billing.assert_store_active(db, store)
    products = list(db.scalars(select(Product).where(Product.store_id == store.id,
                                                     Product.id.in_(body.product_ids))))
    if len(products) != len(set(body.product_ids)):
        raise AppError(404, "not_found", "One or more products were not found in your store")
    for p in products:
        if body.action == "soft_delete":
            catalog.soft_delete(p)
        elif body.action == "restore":
            catalog.restore(p)
        elif body.action == "set_stock":
            v = int(float(body.value or 0))
            if v < 0:
                raise bad_request("Stock cannot be negative")
            p.stock = v
        elif body.action == "adjust_price_percent":
            pct = float(body.value or 0)
            if not -90 <= pct <= 500:
                raise bad_request("Percent must be between -90 and 500")
            p.price = (p.price * Decimal(str(1 + pct / 100))).quantize(Decimal("0.01"))
        elif body.action == "set_category":
            if not body.value or not str(body.value).strip():
                raise bad_request("Category is required")
            p.category = str(body.value).strip().title()[:80]
    db.commit()
    return {"updated": len(products), "action": body.action}


@router.post("/products/import")
async def import_products(file: UploadFile = File(...), store: Store = Depends(current_store),
                          db: Session = Depends(get_db)):
    billing.assert_store_active(db, store)
    content = await file.read()
    return catalog.import_products(db, store, file.filename or "", content)


@router.get("/products-import-template.csv")
def import_template(_: Store = Depends(current_store)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(catalog.IMPORT_COLUMNS)
    w.writerow(["Classic Black Shirt", "Shirts", "2499", "12", "100% cotton, regular fit", "black", "S,M,L", "SH-001"])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=oneseller-products-template.csv"})


@router.post("/images", status_code=201)
async def upload_image(file: UploadFile = File(...), store: Store = Depends(current_store),
                       db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise bad_request("Only JPEG, PNG, WEBP or GIF images are allowed", code="invalid_image_type")
    data = await file.read()
    if len(data) > get_settings().max_image_bytes:
        raise bad_request("Image too large (max 2 MB)", code="image_too_large")
    img = ProductImage(store_id=store.id, content_type=file.content_type, data=data)
    db.add(img)
    db.commit()
    return {"image_id": img.id, "url": catalog.image_url(img.id)}


# ---------------------------------------------------------------- orders

@router.get("/orders")
def list_orders(status: str | None = None, include_sandbox: bool = False, store: Store = Depends(current_store),
                db: Session = Depends(get_db)):
    stmt = select(Order).where(Order.store_id == store.id).options(joinedload(Order.items), joinedload(Order.store))
    if not include_sandbox:
        stmt = stmt.where(Order.is_sandbox.is_(False))
    if status:
        stmt = stmt.where(Order.status == OrderStatus(status))
    return [order_svc.order_out(o, for_seller=True) for o in db.scalars(stmt.order_by(Order.id.desc()).limit(500)).unique()]


@router.get("/orders/{order_id}")
def get_order(order_id: int, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    return order_svc.order_out(order_svc.get_store_order(db, store, order_id), for_seller=True)


@router.patch("/orders/{order_id}")
def update_order(order_id: int, body: OrderStatusUpdate, store: Store = Depends(current_store),
                 db: Session = Depends(get_db)):
    return order_svc.order_out(order_svc.set_status(db, store, order_id, body.status), for_seller=True)


# ---------------------------------------------------------------- billing (mock)

@router.get("/billing")
def billing_status(store: Store = Depends(current_store), db: Session = Depends(get_db)):
    return billing.status(db, store) | {"payments": billing.payments(db, store)}


@router.post("/billing/pay")
def billing_pay(body: PayIn, store: Store = Depends(current_store), db: Session = Depends(get_db)):
    return billing.pay(db, store, body.plan)


@router.post("/billing/simulate-expiry")
def billing_expire(store: Store = Depends(current_store), db: Session = Depends(get_db)):
    return billing.simulate_expiry(db, store)
