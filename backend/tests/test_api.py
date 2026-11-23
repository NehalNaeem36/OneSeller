"""API-level tests: auth, tenant isolation, subscriptions, catalog, deletion integrity, import, checkout."""
from __future__ import annotations

import io
import threading
import uuid

from conftest import checkout, csv_bytes, make_product, register


def test_health_plain_text(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.text == "ok" and r.headers["content-type"].startswith("text/plain")


# ---------------------------------------------------------------- accounts

def test_seller_registration_creates_store_and_trial(client):
    s = register(client, "seller", store_name="Karachi Kicks")
    assert s["store_slug"] == "karachi-kicks"
    billing = client.get("/api/seller/billing", headers=s["headers"]).json()
    assert billing["plan"] == "trial" and billing["status"] == "active"
    assert 27 <= billing["days_remaining"] <= 31
    # second store with the same name gets a different slug
    s2 = register(client, "seller", store_name="Karachi Kicks")
    assert s2["store_slug"] != s["store_slug"]
    assert client.get(f"/api/stores/{s['store_slug']}").status_code == 200


def test_register_validation_and_login(client):
    assert client.post("/api/auth/register", json={"email": "x@test.io", "password": "short", "full_name": "X",
                                                   "role": "customer"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "s@test.io", "password": "password123",
                                                   "full_name": "S", "role": "seller"}).status_code == 400
    register(client, "customer", email="c@test.io")
    assert client.post("/api/auth/register", json={"email": "C@test.io", "password": "password123",
                                                   "full_name": "C", "role": "customer"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "c@test.io", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "c@test.io", "password": "password123"}).status_code == 200


def test_role_guards(client):
    c = register(client, "customer")
    s = register(client, "seller")
    assert client.get("/api/seller/dashboard", headers=c["headers"]).status_code == 403
    assert client.get("/api/cart", headers=s["headers"]).status_code == 403
    assert client.get("/api/seller/dashboard").status_code == 401
    assert client.get("/api/orders", headers={"Authorization": "Bearer forged.token.value"}).status_code == 401


# ---------------------------------------------------------------- isolation

def test_seller_cannot_access_other_sellers_data(client):
    a, b = register(client, "seller"), register(client, "seller")
    p = make_product(client, a)
    for method, path, kw in [("get", f"/api/seller/products/{p['id']}", {}),
                             ("put", f"/api/seller/products/{p['id']}", {"json": {"price": 1}}),
                             ("delete", f"/api/seller/products/{p['id']}", {}),
                             ("post", f"/api/seller/products/{p['id']}/restore", {})]:
        assert getattr(client, method)(path, headers=b["headers"], **kw).status_code == 404
    assert client.post("/api/seller/products/bulk", headers=b["headers"],
                       json={"product_ids": [p["id"]], "action": "soft_delete"}).status_code == 404
    assert client.get("/api/seller/products", headers=b["headers"]).json() == []
    # orders
    c = register(client, "customer")
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": p["id"], "size": "M"})
    order_id = checkout(client, c).json()["orders"][0]["id"]
    assert client.get(f"/api/seller/orders/{order_id}", headers=b["headers"]).status_code == 404
    assert client.patch(f"/api/seller/orders/{order_id}", headers=b["headers"],
                        json={"status": "shipped"}).status_code == 404
    assert client.get("/api/seller/orders", headers=b["headers"]).json() == []
    assert client.get("/api/seller/dashboard", headers=b["headers"]).json()["kpis"]["total_orders"] == 0
    assert client.get(f"/api/seller/orders/{order_id}", headers=a["headers"]).status_code == 200


def test_customer_cannot_access_other_customers_data(client):
    s = register(client, "seller")
    p = make_product(client, s)
    c1, c2 = register(client, "customer"), register(client, "customer")
    client.post("/api/cart/items", headers=c1["headers"], json={"product_id": p["id"], "size": "M"})
    assert client.get("/api/cart", headers=c2["headers"]).json()["items"] == []
    order_id = checkout(client, c1).json()["orders"][0]["id"]
    assert client.get(f"/api/orders/{order_id}", headers=c2["headers"]).status_code == 404
    assert client.get("/api/orders", headers=c2["headers"]).json() == []
    assert len(client.get("/api/orders", headers=c1["headers"]).json()) == 1


def test_seller_cannot_use_foreign_image(client):
    a, b = register(client, "seller"), register(client, "seller")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    img = client.post("/api/seller/images", headers=a["headers"],
                      files={"file": ("x.png", png, "image/png")}).json()
    r = client.post("/api/seller/products", headers=b["headers"],
                    json={"name": "X", "category": "Y", "price": 10, "stock": 1, "image_id": img["image_id"]})
    assert r.status_code == 400
    assert client.get(img["url"]).content == png


# ---------------------------------------------------------------- catalog / search

def test_search_filters(client):
    s = register(client, "seller", store_name="Filter Shop")
    make_product(client, s, name="Black Oxford Shirt", price=2800, sizes=["M", "L"])
    make_product(client, s, name="Black Slim Shirt", price=3500, sizes=["M"])
    make_product(client, s, name="White Linen Shirt", price=2000, colors=["white"], sizes=["S"])
    make_product(client, s, name="Black Jeans", category="Trousers", price=2500, sizes=["32"], stock=0)

    def names(**params):
        return sorted(p["name"] for p in client.get("/api/products", params=params).json()["items"])

    assert names(q="shirts", color="black", size="medium", max_price=3000) == ["Black Oxford Shirt"]
    assert names(category="trousers") == ["Black Jeans"]
    assert names(category="trousers", in_stock=True) == []
    assert names(min_price=2600) == ["Black Oxford Shirt", "Black Slim Shirt"]
    assert names(store="filter shop", color="white") == ["White Linen Shirt"]
    assert names(q="linen") == ["White Linen Shirt"]
    prices = [p["price"] for p in client.get("/api/products", params={"sort": "price_asc"}).json()["items"]]
    assert prices == sorted(prices)
    assert {c["name"] for c in client.get("/api/categories").json()} == {"Shirts", "Trousers"}


# ---------------------------------------------------------------- deletion

def test_soft_delete_restore_and_hard_delete_integrity(client):
    s = register(client, "seller")
    p = make_product(client, s)
    pid = p["id"]
    assert client.delete(f"/api/seller/products/{pid}", headers=s["headers"]).json()["deleted"] == "soft"
    assert client.get(f"/api/products/{pid}").status_code == 404
    assert client.get("/api/products").json()["total"] == 0
    assert len(client.get("/api/seller/products?status=deleted", headers=s["headers"]).json()) == 1
    client.post(f"/api/seller/products/{pid}/restore", headers=s["headers"])
    assert client.get(f"/api/products/{pid}").status_code == 200

    c = register(client, "customer")
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": pid, "size": "M", "quantity": 2})
    order = checkout(client, c).json()["orders"][0]

    # hard delete needs explicit confirmation and is refused while the order is open
    assert client.delete(f"/api/seller/products/{pid}?hard=true", headers=s["headers"]).status_code == 400
    assert client.delete(f"/api/seller/products/{pid}?hard=true&confirm=true", headers=s["headers"]).status_code == 409
    for st in ("shipped", "delivered"):
        assert client.patch(f"/api/seller/orders/{order['id']}", headers=s["headers"], json={"status": st}).status_code == 200
    r = client.delete(f"/api/seller/products/{pid}?hard=true&confirm=true", headers=s["headers"])
    assert r.status_code == 200 and r.json()["recoverable"] is False
    # historical order keeps its snapshot
    hist = client.get(f"/api/orders/{order['id']}", headers=c["headers"]).json()
    assert hist["items"][0]["name"] == "Black Cotton Shirt" and hist["items"][0]["unit_price"] == 2500
    assert hist["items"][0]["product_id"] is None and hist["total"] == 5000


def test_bulk_operations(client):
    s = register(client, "seller")
    ids = [make_product(client, s, name=f"P{i}", sku=f"SKU{i}")["id"] for i in range(3)]
    h = s["headers"]
    assert client.post("/api/seller/products/bulk", headers=h, json={"product_ids": ids, "action": "set_stock",
                                                                     "value": 3}).status_code == 200
    client.post("/api/seller/products/bulk", headers=h, json={"product_ids": ids[:2], "action": "adjust_price_percent",
                                                              "value": 10})
    prods = {p["id"]: p for p in client.get("/api/seller/products", headers=h).json()}
    assert prods[ids[0]]["price"] == 2750 and prods[ids[2]]["price"] == 2500 and prods[ids[1]]["stock"] == 3
    assert client.get("/api/seller/dashboard", headers=h).json()["kpis"]["low_stock_products"] == 3
    client.post("/api/seller/products/bulk", headers=h, json={"product_ids": ids, "action": "soft_delete"})
    assert client.get("/api/products").json()["total"] == 0


# ---------------------------------------------------------------- import

def test_csv_import_with_row_errors_and_upsert(client):
    s = register(client, "seller")
    rows = [["name", "category", "price", "stock", "colors", "sizes", "sku", "description"],
            ["Black Tee", "T-Shirts", "1200", "10", "black, white", "S,M,L", "T1", "Soft tee"],
            ["Bad Price", "T-Shirts", "abc", "5", "", "", "T2", ""],
            ["", "T-Shirts", "100", "5", "", "", "T3", ""],
            ["Blue Jeans", "Trousers", "3,200", "4", "blue", "30,32", "J1", ""]]
    r = client.post("/api/seller/products/import", headers=s["headers"],
                    files={"file": ("products.csv", csv_bytes(rows), "text/csv")}).json()
    assert r["created"] == 2 and r["failed"] == 2 and {e["row"] for e in r["errors"]} == {3, 4}
    found = client.get("/api/products", params={"q": "jeans", "color": "blue", "size": "32"}).json()["items"]
    assert found[0]["price"] == 3200
    # re-import same SKU updates instead of duplicating
    rows2 = [["name", "category", "price", "stock", "sku"], ["Black Tee", "T-Shirts", "999", "7", "T1"]]
    r2 = client.post("/api/seller/products/import", headers=s["headers"],
                     files={"file": ("p.csv", csv_bytes(rows2), "text/csv")}).json()
    assert r2["updated"] == 1 and r2["created"] == 0
    assert len(client.get("/api/seller/products", headers=s["headers"]).json()) == 2


def test_xlsx_import_and_bad_files(client):
    from openpyxl import Workbook
    s = register(client, "seller")
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "category", "price", "stock", "sizes"])
    ws.append(["Leather Wallet", "Accessories", 1500, 20, "Free"])
    ws.append(["Silk Scarf", "Accessories", 2200.5, 3, None])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    r = client.post("/api/seller/products/import", headers=s["headers"], files={"file": ("p.xlsx", buf, xlsx)})
    assert r.json()["created"] == 2
    bad = client.post("/api/seller/products/import", headers=s["headers"],
                      files={"file": ("p.csv", csv_bytes([["title", "cost"], ["x", "1"]]), "text/csv")})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "missing_columns"
    assert client.post("/api/seller/products/import", headers=s["headers"],
                       files={"file": ("p.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 400


# ---------------------------------------------------------------- cart / checkout

def test_cart_validation(client):
    s = register(client, "seller")
    p = make_product(client, s, stock=2)
    c = register(client, "customer")
    h = c["headers"]
    assert client.post("/api/cart/items", headers=h, json={"product_id": p["id"], "size": "XXL"}).status_code == 400
    assert client.post("/api/cart/items", headers=h, json={"product_id": p["id"], "color": "red"}).status_code == 400
    assert client.post("/api/cart/items", headers=h, json={"product_id": p["id"], "quantity": 3}).status_code == 409
    cart = client.post("/api/cart/items", headers=h, json={"product_id": p["id"], "size": "m"}).json()
    assert cart["items"][0]["size"] == "M" and cart["items"][0]["color"] == "black" and cart["total"] == 2500
    assert client.post("/api/cart/items", headers=h, json={"product_id": 99999}).status_code == 404


def test_checkout_transactional_and_split_by_store(client):
    s1, s2 = register(client, "seller"), register(client, "seller")
    p1 = make_product(client, s1, stock=5)
    p2 = make_product(client, s2, name="Hoodie", category="Hoodies", price=4000, stock=1, sizes=[])
    c = register(client, "customer")
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": p1["id"], "size": "M", "quantity": 2})
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": p2["id"]})
    assert checkout(client, c, confirm=False).status_code == 400  # explicit confirmation required
    r = checkout(client, c)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["orders"]) == 2 and data["grand_total"] == 9000
    assert client.get(f"/api/products/{p1['id']}").json()["stock"] == 3
    assert client.get(f"/api/products/{p2['id']}").json()["stock"] == 0
    assert client.get("/api/cart", headers=c["headers"]).json()["items"] == []
    dash = client.get("/api/seller/dashboard", headers=s1["headers"]).json()
    assert dash["kpis"]["total_orders"] == 1 and dash["kpis"]["total_sales"] == 5000
    assert dash["recent_orders"][0]["delivery"]["city"] == "Lahore"


def test_checkout_rolls_back_when_any_line_fails(client):
    s = register(client, "seller")
    p1 = make_product(client, s, stock=5)
    p2 = make_product(client, s, name="Last One", stock=1, sizes=[])
    c1, c2 = register(client, "customer"), register(client, "customer")
    client.post("/api/cart/items", headers=c1["headers"], json={"product_id": p1["id"], "size": "M", "quantity": 2})
    client.post("/api/cart/items", headers=c1["headers"], json={"product_id": p2["id"]})
    client.post("/api/cart/items", headers=c2["headers"], json={"product_id": p2["id"]})
    assert checkout(client, c2).status_code == 200  # c2 buys the last unit first
    r = checkout(client, c1)
    assert r.status_code == 409 and r.json()["error"]["code"] in ("insufficient_stock",)
    assert client.get(f"/api/products/{p1['id']}").json()["stock"] == 5  # nothing partially committed
    assert client.get("/api/orders", headers=c1["headers"]).json() == []


def test_checkout_idempotency(client):
    s = register(client, "seller")
    p = make_product(client, s, stock=5)
    c = register(client, "customer")
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": p["id"], "size": "M"})
    key = uuid.uuid4().hex
    first = checkout(client, c, key=key).json()
    second = checkout(client, c, key=key).json()
    assert [o["id"] for o in first["orders"]] == [o["id"] for o in second["orders"]]
    assert len(client.get("/api/orders", headers=c["headers"]).json()) == 1
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 4


def test_no_oversell_under_concurrency(client):
    s = register(client, "seller")
    p = make_product(client, s, stock=3, sizes=[])
    customers = [register(client, "customer") for _ in range(6)]
    for c in customers:
        assert client.post("/api/cart/items", headers=c["headers"], json={"product_id": p["id"]}).status_code == 200
    results = []

    def buy(c):
        results.append(checkout(client, c).status_code)

    threads = [threading.Thread(target=buy, args=(c,)) for c in customers]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(200) == 3
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 0


def test_cancel_restores_stock_and_transitions(client):
    s = register(client, "seller")
    p = make_product(client, s, stock=5)
    c = register(client, "customer")
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": p["id"], "size": "M", "quantity": 2})
    oid = checkout(client, c).json()["orders"][0]["id"]
    h = s["headers"]
    assert client.patch(f"/api/seller/orders/{oid}", headers=h, json={"status": "delivered"}).status_code == 400
    assert client.patch(f"/api/seller/orders/{oid}", headers=h, json={"status": "cancelled"}).status_code == 200
    assert client.get(f"/api/products/{p['id']}").json()["stock"] == 5
    assert client.patch(f"/api/seller/orders/{oid}", headers=h, json={"status": "processing"}).status_code == 400


# ---------------------------------------------------------------- subscriptions

def test_subscription_expiry_enforced_in_backend_and_renewal(client):
    s = register(client, "seller")
    p = make_product(client, s)
    c = register(client, "customer")
    client.post("/api/cart/items", headers=c["headers"], json={"product_id": p["id"], "size": "M"})
    status = client.post("/api/seller/billing/simulate-expiry", headers=s["headers"]).json()
    assert status["status"] == "expired"
    r = client.post("/api/seller/products", headers=s["headers"],
                    json={"name": "X", "category": "Y", "price": 10, "stock": 1})
    assert r.status_code == 402 and r.json()["error"]["code"] == "subscription_expired"
    assert client.get("/api/products").json()["total"] == 0  # hidden from marketplace
    assert checkout(client, c).status_code in (404, 409)
    paid = client.post("/api/seller/billing/pay", headers=s["headers"], json={"plan": "premium"}).json()
    assert paid["status"] == "active" and paid["plan"] == "premium" and paid["payment_reference"].startswith("MOCK-")
    item = client.get("/api/products").json()["items"][0]
    assert item["store"]["premium"] is True
    assert client.get("/api/home").json()["premium_products"][0]["id"] == p["id"]
    # renewal of the same active plan extends from the current period end
    renewed = client.post("/api/seller/billing/pay", headers=s["headers"], json={"plan": "premium"}).json()
    assert renewed["action"] == "renewed" and renewed["days_remaining"] > paid["days_remaining"] + 25
    assert len(client.get("/api/seller/billing", headers=s["headers"]).json()["payments"]) == 2


def test_order_limit_enforced(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "trial_order_limit", 1)
    s = register(client, "seller")
    p = make_product(client, s, stock=10)
    for expected in (200, 409):
        c = register(client, "customer")
        client.post("/api/cart/items", headers=c["headers"], json={"product_id": p["id"], "size": "M"})
        r = checkout(client, c)
        assert r.status_code == expected, r.text
    assert r.json()["error"]["code"] == "store_order_limit"


def test_memory_endpoints(client):
    from app.db import SessionLocal
    from app.services import memory
    c = register(client, "customer")
    with SessionLocal() as db:
        memory.remember(db, f"user:{c['user']['id']}", "preferred_colors", "black")
    assert client.get("/api/me/memory", headers=c["headers"]).json() == {"preferred_colors": "black"}
    assert client.delete("/api/me/memory", headers=c["headers"]).json() == {}
