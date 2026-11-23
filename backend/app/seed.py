"""Idempotent demo data: 4 stores (one premium), ~30 products, demo customer.  python -m app.seed"""
from __future__ import annotations

from sqlalchemy import select

from .db import SessionLocal
from .models import Role, Store, User
from .routers.auth import unique_slug
from .security import hash_password
from .services import billing, catalog

DEMO_PASSWORD = "demo12345"

STORES = [
    {
        "email": "urbanthreads@demo.oneseller.ai", "owner": "Ayesha Khan", "name": "Urban Threads",
        "tagline": "Everyday menswear, made in Lahore", "color": "#0f766e", "premium": True,
        "products": [
            ("Classic Black Oxford Shirt", "Shirts", 2799, 14, "black", "S,M,L,XL", "Crisp cotton oxford, regular fit."),
            ("Slim Fit Black Poplin Shirt", "Shirts", 2299, 9, "black", "M,L", "Lightweight poplin, slim fit."),
            ("White Linen Shirt", "Shirts", 3199, 11, "white", "S,M,L", "Breathable linen for summer."),
            ("Navy Check Casual Shirt", "Shirts", 2599, 6, "navy", "M,L,XL", "Soft brushed cotton checks."),
            ("Charcoal Chino Trousers", "Trousers", 3499, 10, "charcoal,khaki", "30,32,34,36", "Stretch cotton chinos."),
            ("Black Crew Neck T-Shirt", "T-Shirts", 1299, 25, "black,white,gray", "S,M,L,XL", "Heavyweight combed cotton tee."),
            ("Olive Bomber Jacket", "Jackets", 6999, 4, "olive", "M,L", "Water-resistant shell, quilted lining."),
        ],
    },
    {
        "email": "rangrez@demo.oneseller.ai", "owner": "Bilal Ahmed", "name": "Rangrez Studio",
        "tagline": "Hand-block printed kurtas and eastern wear", "color": "#b45309", "premium": False,
        "products": [
            ("Black Embroidered Kurta Shirt", "Shirts", 2950, 3, "black", "M,L", "Short kurta-style shirt with fine embroidery."),
            ("Maroon Block Print Kurta", "Kurtas", 3800, 8, "maroon", "S,M,L", "Hand block printed lawn kurta."),
            ("White Cotton Shalwar Kameez", "Shalwar Kameez", 5200, 5, "white", "M,L,XL", "Classic wash-and-wear suit."),
            ("Mustard Silk Dupatta", "Accessories", 1800, 12, "mustard", "Free", "Pure silk, hand-dyed."),
            ("Teal Printed Kurta", "Kurtas", 3400, 0, "teal", "S,M", "Soft lawn print (restocking soon)."),
            ("Black Peshawari Chappal", "Shoes", 4200, 7, "black,brown", "40,41,42,43,44", "Handmade leather chappal."),
        ],
    },
    {
        "email": "stridesneakers@demo.oneseller.ai", "owner": "Usman Tariq", "name": "Stride Sneakers",
        "tagline": "Comfort-first sneakers and sportswear", "color": "#1d4ed8", "premium": False,
        "products": [
            ("Cloud Runner Sneakers", "Shoes", 7499, 9, "white,black", "40,41,42,43,44", "Lightweight running shoe."),
            ("Court Classic White Sneakers", "Shoes", 5999, 12, "white", "39,40,41,42,43", "Leather court sneaker."),
            ("Black Training Hoodie", "Hoodies", 3999, 8, "black,gray", "S,M,L,XL", "Fleece-lined training hoodie."),
            ("Dry-Fit Black Sports Shirt", "Shirts", 1899, 20, "black,blue", "S,M,L,XL", "Moisture-wicking sports shirt."),
            ("Gray Jogger Pants", "Trousers", 2899, 15, "gray,black", "S,M,L", "Tapered cotton joggers."),
            ("Canvas Backpack", "Bags", 3299, 6, "black,olive", "Free", "20L everyday backpack."),
        ],
    },
    {
        "email": "lumiere@demo.oneseller.ai", "owner": "Sana Malik", "name": "Lumiere Boutique",
        "tagline": "Elegant womenswear and accessories", "color": "#be185d", "premium": False,
        "products": [
            ("Black Satin Blouse", "Shirts", 3299, 7, "black,cream", "S,M,L", "Fluid satin with covered buttons."),
            ("Floral Midi Dress", "Dresses", 5499, 6, "pink,blue", "S,M,L", "Chiffon midi with lining."),
            ("Beige Trench Coat", "Jackets", 9999, 3, "beige", "M,L", "Double-breasted classic trench."),
            ("Leather Tote Bag", "Bags", 6499, 5, "brown,black", "Free", "Genuine leather, spacious."),
            ("Silver Minimal Watch", "Watches", 4999, 10, "silver", "Free", "Stainless steel, 36mm."),
            ("Black Abaya with Lace Trim", "Abayas", 6200, 4, "black", "S,M,L,XL", "Nida fabric with lace detailing."),
        ],
    },
]


def _ensure_seller(db, spec) -> Store:
    user = db.scalars(select(User).where(User.email == spec["email"])).first()
    if user:
        return db.scalars(select(Store).where(Store.owner_id == user.id)).one()
    user = User(email=spec["email"], password_hash=hash_password(DEMO_PASSWORD), role=Role.seller,
                full_name=spec["owner"])
    db.add(user)
    db.flush()
    store = Store(owner_id=user.id, name=spec["name"], slug=unique_slug(db, spec["name"]), tagline=spec["tagline"],
                  description=f"{spec['name']} — {spec['tagline']}.", brand_color=spec["color"])
    db.add(store)
    db.flush()
    billing.start_trial(db, store)
    db.flush()
    for i, (name, cat, price, stock, colors, sizes, desc) in enumerate(spec["products"], 1):
        catalog.create_product(db, store, {"name": name, "category": cat, "price": price, "stock": stock,
                                           "colors": colors, "sizes": sizes, "description": desc,
                                           "sku": f"{store.slug[:6].upper()}-{i:03d}"})
    db.commit()
    if spec["premium"]:
        billing.pay(db, store, "premium")
    return store


def seed() -> None:
    with SessionLocal() as db:
        for spec in STORES:
            _ensure_seller(db, spec)
        if not db.scalars(select(User).where(User.email == "customer@demo.oneseller.ai")).first():
            db.add(User(email="customer@demo.oneseller.ai", password_hash=hash_password(DEMO_PASSWORD),
                        role=Role.customer, full_name="Demo Customer", phone="03001234567",
                        address="House 12, Street 4, Gulberg III", city="Lahore"))
            db.commit()
    print("Seed complete. Demo password for all demo accounts:", DEMO_PASSWORD)


if __name__ == "__main__":
    seed()
