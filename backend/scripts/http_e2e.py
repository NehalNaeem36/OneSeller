"""HTTP end-to-end check against a running backend (default http://localhost:8000), mirroring the spec's demo:
seller registers → trial → customizes store → imports CSV → products in marketplace → customer chats with the agent
→ order via agent confirmation → seller sees order → new thread recalls preferences.
Usage: uv run python scripts/http_e2e.py [base_url]"""
import io, sys, time, uuid
import httpx

B = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
c = httpx.Client(base_url=B, timeout=180)
tag = uuid.uuid4().hex[:6]
ok = lambda cond, msg: print(("PASS " if cond else "FAIL ") + msg) or cond
results = []

def reg(role, **kw):
    body = {"email": f"{role}-{tag}@e2e-oneseller.com", "password": "password123", "full_name": f"E2E {role}", "role": role, **kw}
    r = c.post("/api/auth/register", json=body); r.raise_for_status(); d = r.json()
    d["h"] = {"Authorization": f"Bearer {d['token']}"}; return d

results.append(ok(c.get("/health").text == "ok", "GET /health -> ok"))
s = reg("seller", store_name=f"E2E Shirts {tag}")
bill = c.get("/api/seller/billing", headers=s["h"]).json()
results.append(ok(bill["plan"] == "trial" and bill["status"] == "active", f"seller trial active ({bill['days_remaining']} days)"))
c.put("/api/seller/store", headers=s["h"], json={"tagline": "E2E tagline", "brand_color": "#123456"}).raise_for_status()
csv = ("name,category,price,stock,colors,sizes,sku\n"
       f"E2E Midnight Shirt {tag},Shirts,2450,6,black,\"S,M,L\",E2E-1\n"
       f"E2E Onyx Shirt {tag},Shirts,2150,4,black,\"M,L\",E2E-2\n"
       f"E2E Snow Shirt {tag},Shirts,1800,9,white,M,E2E-3\n")
imp = c.post("/api/seller/products/import", headers=s["h"], files={"file": ("p.csv", io.BytesIO(csv.encode()), "text/csv")}).json()
results.append(ok(imp["created"] == 3, f"CSV import created {imp['created']}"))
found = c.get("/api/products", params={"q": f"e2e {tag}", "color": "black", "size": "M", "max_price": 3000}).json()
results.append(ok(found["total"] == 2, f"marketplace search finds {found['total']} black M shirts"))

cust = reg("customer")
c.put("/api/me", headers=cust["h"], json={"phone": "03001234567", "address": "House 1 Street 2 Gulberg", "city": "Lahore"})
def chat(msg, thread="e2e-1"):
    t0 = time.time(); r = c.post("/api/chat", headers=cust["h"], json={"thread_id": thread, "message": msg}).json()
    print(f"   [{time.time()-t0:.1f}s] {msg!r} -> tools={[t['name'] for t in r['tool_calls']]} tokens={r['tokens']}\n      {r['reply'][:220]!r}")
    return r
r1 = chat(f"I usually wear size M. Show me black E2E shirts {tag} under Rs. 3000 in medium size")
results.append(ok(any(t["name"] == "search_products" for t in r1["tool_calls"]) and "Onyx" in r1["reply"], "agent searched catalog"))
r2 = chat("Which one is cheaper?")
results.append(ok("Onyx" in r2["reply"], "agent compared from memory (Onyx is cheaper)"))
r3 = chat("Add the cheaper one to my cart")
cart = c.get("/api/cart", headers=cust["h"]).json()
results.append(ok(len(cart["items"]) == 1 and "Onyx" in cart["items"][0]["name"], "agent added the cheaper product to the real cart"))
r4 = chat("checkout")
results.append(ok("Reply **yes**" in r4["reply"], "agent showed confirmation summary"))
r5 = chat("yes")
orders = c.get("/api/orders", headers=cust["h"]).json()
results.append(ok(len(orders) == 1 and orders[0]["channel"] == "agent" and "confirmed" in r5["reply"], "order created after explicit yes"))
prod = c.get("/api/products", params={"q": f"onyx {tag}"}).json()["items"][0]
results.append(ok(prod["stock"] == 3, f"inventory decremented (stock {prod['stock']})"))
so = c.get("/api/seller/orders", headers=s["h"]).json()
results.append(ok(len(so) == 1 and so[0]["delivery"]["city"] == "Lahore", "seller sees the order with delivery details"))
mem = c.get("/api/me/memory", headers=cust["h"]).json()
results.append(ok(mem.get("preferred_sizes") == "M", f"long-term memory saved {mem}"))
r6 = chat("What size do I usually wear?", thread="e2e-2")
results.append(ok(" M" in r6["reply"] or "M." in r6["reply"] or "size M" in r6["reply"], "new thread recalls preference"))
other = reg("customer") if False else None
print(f"\n{sum(results)}/{len(results)} checks passed")
