"""Public marketplace browsing (no private data)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..errors import not_found
from ..models import Order, OrderStatus, Plan, Product, ProductImage, Store, Subscription
from ..services import catalog

router = APIRouter(prefix="/api", tags=["marketplace"])


def _live_stores_stmt():
    return (select(Store).join(Subscription, Subscription.store_id == Store.id)
            .where(Store.is_active.is_(True), Subscription.period_end > catalog.now_utc())
            .options(joinedload(Store.subscription)))


def _store_card(db: Session, s: Store, count: int | None = None) -> dict:
    if count is None:
        count = db.scalar(select(func.count(Product.id)).where(Product.store_id == s.id, Product.is_active.is_(True)))
    return {"id": s.id, "name": s.name, "slug": s.slug, "tagline": s.tagline, "description": s.description,
            "brand_color": s.brand_color, "logo_url": catalog.image_url(s.logo_image_id),
            "premium": catalog.is_premium(s), "product_count": count or 0}


def store_search(db: Session, q: str | None, limit: int = 24) -> list[dict]:
    stmt = _live_stores_stmt()
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Store.name).like(like) | func.lower(func.coalesce(Store.description, "")).like(like)
                          | func.lower(func.coalesce(Store.tagline, "")).like(like))
    stores = list(db.scalars(stmt.limit(200)).unique())
    stores.sort(key=lambda s: (not catalog.is_premium(s), s.name.lower()))
    return [_store_card(db, s) for s in stores[:limit]]


@router.get("/products")
def products(
    q: str | None = None, category: str | None = None, color: str | None = None, size: str | None = None,
    min_price: float | None = Query(None, ge=0), max_price: float | None = Query(None, ge=0),
    store: str | None = None, in_stock: bool = False,
    sort: str = Query("relevance", pattern="^(relevance|price_asc|price_desc|newest)$"),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(24, ge=1, le=60),
    db: Session = Depends(get_db),
):
    rows, total = catalog.search_products(db, query=q, category=category, color=color, size=size,
                                          min_price=min_price, max_price=max_price, store=store,
                                          in_stock_only=in_stock, sort=sort, limit=page_size,
                                          offset=(page - 1) * page_size)
    return {"items": [catalog.product_out(p) for p in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/products/{product_id}")
def product_detail(product_id: int, db: Session = Depends(get_db)):
    return catalog.product_out(catalog.get_visible_product(db, product_id))


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    return catalog.list_categories(db)


@router.get("/stores")
def stores(q: str | None = None, db: Session = Depends(get_db)):
    return store_search(db, q)


@router.get("/stores/{slug}")
def store_detail(slug: str, db: Session = Depends(get_db)):
    s = db.scalars(_live_stores_stmt().where(Store.slug == slug)).first()
    if not s:
        raise not_found("Store")
    return _store_card(db, s)


@router.get("/home")
def home(db: Session = Depends(get_db)):
    """Landing page sections computed from real data."""
    base = catalog.visible_products_query().options(joinedload(Product.store).joinedload(Store.subscription))
    premium = list(db.scalars(base.where(Subscription.plan == Plan.premium, Product.stock > 0)
                              .order_by(Product.created_at.desc()).limit(8)).unique())
    since = catalog.now_utc() - timedelta(days=30)
    top_rows = db.execute(select(Order.store_id, func.count(Order.id).label("n"))
                          .where(Order.created_at >= since, Order.status != OrderStatus.cancelled,
                                 Order.is_sandbox.is_(False))
                          .group_by(Order.store_id).order_by(func.count(Order.id).desc()).limit(5)).all()
    top_ids = [r[0] for r in top_rows]
    top_products = []
    if top_ids:
        top_products = list(db.scalars(base.where(Product.store_id.in_(top_ids), Product.stock > 0)
                                       .limit(40)).unique())
        top_products.sort(key=lambda p: top_ids.index(p.store_id))
    featured = list(db.scalars(base.where(Product.stock > 0).order_by(Product.created_at.desc()).limit(12)).unique())
    top_store_objs = [db.get(Store, i) for i in top_ids]
    return {
        "premium_products": [catalog.product_out(p) for p in premium],
        "top_seller_products": [catalog.product_out(p) for p in top_products[:8]],
        "featured_products": [catalog.product_out(p) for p in featured],
        "categories": catalog.list_categories(db)[:12],
        "top_stores": [_store_card(db, s) for s in top_store_objs if s],
        "stores": store_search(db, None, limit=8),
    }


@router.get("/images/{image_id}")
def image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(ProductImage, image_id)
    if not img:
        raise not_found("Image")
    return Response(content=img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=86400"})
