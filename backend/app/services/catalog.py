"""Catalog: normalization, search, product CRUD (tenant-scoped), CSV/XLSX import."""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..errors import AppError, bad_request, not_found
from ..models import OPEN_ORDER_STATUSES, Order, OrderItem, Plan, Product, Store, Subscription

# ---------------------------------------------------------------- normalization

SIZE_SYNONYMS = {
    "extra small": "xs", "x-small": "xs", "xsmall": "xs", "xs": "xs",
    "small": "s", "s": "s",
    "medium": "m", "med": "m", "m": "m",
    "large": "l", "l": "l",
    "extra large": "xl", "x-large": "xl", "xlarge": "xl", "xl": "xl",
    "xxl": "xxl", "2xl": "xxl", "xx-large": "xxl", "xxxl": "xxxl", "3xl": "xxxl",
    "free size": "free", "free": "free", "one size": "free",
}
COLOR_SYNONYMS = {"grey": "gray", "navy blue": "navy", "off white": "off-white", "offwhite": "off-white"}
KNOWN_COLORS = {
    "black", "white", "gray", "red", "blue", "navy", "green", "yellow", "orange", "pink", "purple",
    "brown", "beige", "maroon", "olive", "teal", "cream", "gold", "silver", "khaki", "off-white",
    "charcoal", "mustard", "peach", "lavender", "sky", "multicolor",
}
STOPWORDS = {
    "show", "me", "i", "want", "need", "some", "any", "the", "a", "an", "for", "under", "below", "less",
    "than", "over", "above", "in", "size", "sizes", "color", "colour", "with", "and", "or", "of", "please",
    "find", "search", "looking", "look", "get", "buy", "rs", "pkr", "rupees", "price", "priced", "cheap",
    "available", "stock", "do", "you", "have", "is", "are", "there", "what", "which", "my", "to", "up",
    "options", "option", "products", "product", "items", "item", "something", "can", "could", "would",
    "like", "around", "between", "within", "budget", "max", "maximum", "minimum", "min", "from", "at",
    "most", "least", "best", "good", "nice", "new", "on", "by", "store", "shop", "all", "list", "only",
}


def norm_size(s: str) -> str:
    s = s.strip().lower()
    return SIZE_SYNONYMS.get(s, s)


def norm_color(c: str) -> str:
    c = c.strip().lower()
    return COLOR_SYNONYMS.get(c, c)


def encode_list(values, normalizer) -> str:
    if isinstance(values, str):
        values = re.split(r"[,;/|]", values)
    out: list[str] = []
    for v in values or []:
        v = normalizer(str(v))
        if v and v not in out:
            out.append(v)
    return "," + ",".join(out) + ("," if out else "")


def decode_list(text: str | None) -> list[str]:
    return [v for v in (text or "").split(",") if v]


def display_size(s: str) -> str:
    return s.upper() if len(s) <= 4 and s.isalpha() and s != "free" else s.title()


def stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("sses", "shes", "ches", "xes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower().replace("-", "")).strip()


PRICE_MAX_RE = re.compile(r"(?:under|below|less than|upto|up to|max(?:imum)?|within|<=?|budget(?: of| is)?)\s*(?:rs\.?|pkr|rupees)?\s*([\d,]+(?:\.\d+)?)\s*(k)?", re.I)
PRICE_MIN_RE = re.compile(r"(?:over|above|more than|at least|min(?:imum)?|>=?)\s*(?:rs\.?|pkr|rupees)?\s*([\d,]+(?:\.\d+)?)\s*(k)?", re.I)
PRICE_RANGE_RE = re.compile(r"between\s*(?:rs\.?|pkr)?\s*([\d,]+)\s*(k)?\s*(?:and|-|to)\s*(?:rs\.?|pkr)?\s*([\d,]+)\s*(k)?", re.I)
SIZE_RE = re.compile(r"\b(extra small|extra large|x-small|x-large|xx-large|small|medium|large|xxxl|xxl|3xl|2xl|xl|xs|free size|one size)\b|\bsize\s+(xs|s|m|l|xl|xxl|xxxl|\d{2,3})\b", re.I)


def _num(v: str, k: str | None) -> float:
    n = float(v.replace(",", ""))
    return n * 1000 if k else n


def parse_free_text(text: str) -> dict:
    """Extract structured filters from natural language (fallback when the LLM leaves them in `query`)."""
    out: dict = {}
    t = text or ""
    if m := PRICE_RANGE_RE.search(t):
        out["min_price"] = _num(m.group(1), m.group(2))
        out["max_price"] = _num(m.group(3), m.group(4))
    else:
        if m := PRICE_MAX_RE.search(t):
            out["max_price"] = _num(m.group(1), m.group(2))
        if m := PRICE_MIN_RE.search(t):
            out["min_price"] = _num(m.group(1), m.group(2))
    if m := SIZE_RE.search(t):
        out["size"] = norm_size(m.group(1) or m.group(2))
    low = t.lower().replace("navy blue", "navy").replace("off white", "off-white")
    for word in re.findall(r"[a-z\-]+", low):
        w = norm_color(word)
        if w in KNOWN_COLORS:
            out["color"] = w
            break
    return out


def keyword_tokens(text: str, drop: set[str] | None = None) -> list[str]:
    drop = drop or set()
    toks = []
    for raw in _norm_text(text or "").split():
        if raw in STOPWORDS or raw in drop or raw.isdigit() or len(raw) < 2:
            continue
        if raw in SIZE_SYNONYMS or norm_color(raw) in KNOWN_COLORS:
            continue
        if re.fullmatch(r"\d+k", raw):
            continue
        toks.append(stem(raw))
    return toks


# ---------------------------------------------------------------- serialization

def money(v) -> float:
    return float(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def image_url(image_id: int | None) -> str | None:
    return f"/api/images/{image_id}" if image_id else None


def is_premium(store: Store) -> bool:
    sub = store.subscription
    return bool(sub and sub.plan == Plan.premium and as_utc(sub.period_end) > now_utc())


def product_out(p: Product, *, private: bool = False) -> dict:
    s = get_settings()
    data = {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "price": money(p.price),
        "currency": s.currency,
        "colors": decode_list(p.colors),
        "sizes": [display_size(z) for z in decode_list(p.sizes)],
        "stock": p.stock,
        "in_stock": p.stock > 0,
        "image_url": image_url(p.image_id),
        "store": {"id": p.store.id, "name": p.store.name, "slug": p.store.slug,
                  "premium": is_premium(p.store)} if p.store else None,
    }
    if private:
        data.update({"sku": p.sku, "is_active": p.is_active, "image_id": p.image_id,
                     "deleted_at": p.deleted_at.isoformat() if p.deleted_at else None,
                     "low_stock": p.stock <= s.low_stock_threshold})
    return data


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- public search

def visible_products_query():
    """Products visible on the marketplace: active product, active store, live subscription."""
    return (
        select(Product)
        .join(Store, Product.store_id == Store.id)
        .join(Subscription, Subscription.store_id == Store.id)
        .where(Product.is_active.is_(True), Store.is_active.is_(True),
               Subscription.period_end > now_utc())
    )


def search_products(
    db: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    color: str | None = None,
    size: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    store: str | None = None,
    in_stock_only: bool = False,
    sort: str = "relevance",
    limit: int = 20,
    offset: int = 0,
    parse_query: bool = False,
) -> tuple[list[Product], int]:
    if parse_query and query:
        parsed = parse_free_text(query)
        color = color or parsed.get("color")
        size = size or parsed.get("size")
        if min_price is None:
            min_price = parsed.get("min_price")
        if max_price is None:
            max_price = parsed.get("max_price")

    stmt = visible_products_query().options(joinedload(Product.store).joinedload(Store.subscription))
    if category:
        stmt = stmt.where(func.lower(Product.category).like(f"%{category.strip().lower()}%"))
    if color:
        stmt = stmt.where(Product.colors.like(f"%,{norm_color(color)},%"))
    if size:
        stmt = stmt.where(Product.sizes.like(f"%,{norm_size(size)},%"))
    if min_price is not None:
        stmt = stmt.where(Product.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.price <= max_price)
    if store:
        st = store.strip().lower()
        stmt = stmt.where((func.lower(Store.name).like(f"%{st}%")) | (Store.slug == st))
    if in_stock_only:
        stmt = stmt.where(Product.stock > 0)

    candidates = list(db.scalars(stmt.limit(3000)).unique())
    tokens = keyword_tokens(query or "", drop={(category or "").lower()} if category else None)

    scored: list[tuple[float, Product]] = []
    for p in candidates:
        if tokens:
            name = _norm_text(p.name)
            hay = " ".join([name, _norm_text(p.category), _norm_text(p.description or ""),
                            _norm_text(p.store.name)])
            if not all(t in hay for t in tokens):
                continue
            score = sum(3 if t in name else 1 for t in tokens)
        else:
            score = 0
        score += 0.5 if p.stock > 0 else 0
        scored.append((score, p))

    if sort == "price_asc":
        scored.sort(key=lambda x: (money(x[1].price), x[1].id))
    elif sort == "price_desc":
        scored.sort(key=lambda x: (-money(x[1].price), x[1].id))
    elif sort == "newest":
        scored.sort(key=lambda x: -x[1].id)
    else:
        scored.sort(key=lambda x: (-x[0], money(x[1].price), x[1].id))
    total = len(scored)
    return [p for _, p in scored[offset: offset + limit]], total


def get_visible_product(db: Session, product_id: int) -> Product:
    p = db.scalars(
        visible_products_query().where(Product.id == product_id)
        .options(joinedload(Product.store).joinedload(Store.subscription))
    ).first()
    if not p:
        raise not_found("Product")
    return p


def list_categories(db: Session) -> list[dict]:
    rows = db.execute(
        visible_products_query().with_only_columns(Product.category, func.count(Product.id))
        .group_by(Product.category).order_by(func.count(Product.id).desc())
    ).all()
    return [{"name": c, "count": n} for c, n in rows]


# ---------------------------------------------------------------- seller CRUD (tenant scoped)

def get_owned_product(db: Session, store: Store, product_id: int) -> Product:
    p = db.scalars(select(Product).where(Product.id == product_id, Product.store_id == store.id)).first()
    if not p:
        raise not_found("Product")  # 404 even if it exists in another store (no ID probing)
    return p


def _validate_image(db: Session, store: Store, image_id: int | None) -> None:
    from ..models import ProductImage
    if image_id is None:
        return
    img = db.get(ProductImage, image_id)
    if not img or img.store_id != store.id:
        raise bad_request("Image not found in your store", code="invalid_image")


def create_product(db: Session, store: Store, data: dict) -> Product:
    _validate_image(db, store, data.get("image_id"))
    p = Product(
        store_id=store.id,
        name=data["name"].strip(),
        description=(data.get("description") or "").strip() or None,
        category=data["category"].strip().title(),
        price=Decimal(str(data["price"])).quantize(Decimal("0.01")),
        stock=int(data["stock"]),
        colors=encode_list(data.get("colors") or [], norm_color),
        sizes=encode_list(data.get("sizes") or [], norm_size),
        sku=(data.get("sku") or None),
        image_id=data.get("image_id"),
        is_active=data.get("is_active", True),
    )
    db.add(p)
    return p


def update_product(db: Session, store: Store, product: Product, data: dict) -> Product:
    if "image_id" in data:
        _validate_image(db, store, data["image_id"])
    for field in ("name", "description", "sku", "image_id", "stock"):
        if field in data:
            setattr(product, field, data[field])
    if "category" in data and data["category"]:
        product.category = data["category"].strip().title()
    if "price" in data and data["price"] is not None:
        product.price = Decimal(str(data["price"])).quantize(Decimal("0.01"))
    if "colors" in data and data["colors"] is not None:
        product.colors = encode_list(data["colors"], norm_color)
    if "sizes" in data and data["sizes"] is not None:
        product.sizes = encode_list(data["sizes"], norm_size)
    if "is_active" in data and data["is_active"] is not None:
        product.is_active = data["is_active"]
        product.deleted_at = None if data["is_active"] else (product.deleted_at or now_utc())
    return product


def soft_delete(product: Product) -> None:
    product.is_active = False
    product.deleted_at = now_utc()


def restore(product: Product) -> None:
    product.is_active = True
    product.deleted_at = None


def hard_delete(db: Session, product: Product) -> None:
    """Permanent delete. Refused while the product sits in an open order; order_items keep snapshots."""
    open_refs = db.scalar(
        select(func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.product_id == product.id, Order.status.in_(OPEN_ORDER_STATUSES))
    )
    if open_refs:
        raise AppError(409, "product_in_open_orders",
                       "This product is part of orders that are not yet delivered or cancelled. "
                       "Soft-delete it instead, or hard-delete after those orders are closed.")
    db.execute(update(OrderItem).where(OrderItem.product_id == product.id).values(product_id=None))
    db.delete(product)


# ---------------------------------------------------------------- CSV / XLSX import

IMPORT_COLUMNS = ["name", "category", "price", "stock", "description", "colors", "sizes", "sku"]
REQUIRED_COLUMNS = {"name", "category", "price", "stock"}


def _rows_from_upload(filename: str, content: bytes) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(h or "").strip().lower() for h in rows[0]]
        out = []
        for r in rows[1:]:
            if r is None or all(c in (None, "") for c in r):
                continue
            out.append({header[i]: ("" if c is None else str(c).strip()) for i, c in enumerate(r) if i < len(header)})
        return out
    raise bad_request("Unsupported file type. Upload a .csv or .xlsx file.", code="unsupported_file")


def import_products(db: Session, store: Store, filename: str, content: bytes, *, upsert_by_sku: bool = True) -> dict:
    if len(content) > 5 * 1024 * 1024:
        raise bad_request("File too large (max 5 MB)", code="file_too_large")
    rows = _rows_from_upload(filename, content)
    if not rows:
        raise bad_request("The file has no data rows", code="empty_file")
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise bad_request(f"Missing required columns: {', '.join(sorted(missing))}", code="missing_columns",
                          expected=IMPORT_COLUMNS)
    if len(rows) > 2000:
        raise bad_request("Too many rows (max 2000 per import)", code="too_many_rows")

    created, updated, errors = 0, 0, []
    for idx, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            name = row.get("name", "").strip()
            category = row.get("category", "").strip()
            if not name or not category:
                raise ValueError("name and category are required")
            price = float(str(row.get("price", "")).replace(",", ""))
            stock = int(float(str(row.get("stock", "0")).replace(",", "") or 0))
            if price <= 0:
                raise ValueError("price must be greater than 0")
            if stock < 0:
                raise ValueError("stock cannot be negative")
            data = {"name": name[:200], "category": category[:80], "price": price, "stock": stock,
                    "description": row.get("description") or None, "colors": row.get("colors", ""),
                    "sizes": row.get("sizes", ""), "sku": (row.get("sku") or None)}
            existing = None
            if upsert_by_sku and data["sku"]:
                existing = db.scalars(select(Product).where(Product.store_id == store.id,
                                                            Product.sku == data["sku"])).first()
            with db.begin_nested():
                if existing:
                    update_product(db, store, existing, data)
                    restore(existing)
                    updated += 1
                else:
                    create_product(db, store, data)
                    created += 1
                db.flush()
        except Exception as exc:  # collect per-row errors, keep importing valid rows
            errors.append({"row": idx, "error": str(exc)[:200]})
    db.commit()
    return {"created": created, "updated": updated, "failed": len(errors), "errors": errors[:100]}
