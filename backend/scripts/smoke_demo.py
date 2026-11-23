"""Run the spec's end-to-end demo conversation in-process against the configured LLM.
Usage (from backend/):  PYTHONPATH=. uv run python scripts/smoke_demo.py [user_id]"""
import sys
import time

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
uid = sys.argv[1] if len(sys.argv) > 1 else f"smoke-{int(time.time())}"
print("health:", c.get("/health").text)
turns = ["Show me black shirts under Rs. 3000 in medium size", "Which one is cheaper?",
         "Add the cheaper one to my cart", "I want to checkout",
         "My name is Ali Raza, phone 03211234567, address House 5 Street 9 DHA Phase 5, city Lahore",
         "yes"]
for t in turns:
    t0 = time.time()
    r = c.post("/chat", json={"user_id": uid, "thread_id": "t1", "message": t}).json()
    print(f"\n>>> {t}\n[{time.time()-t0:.1f}s] tools={[(x['name'], x['args'], x['ok']) for x in r['tool_calls']]} "
          f"tokens={r['tokens']}\n{r['reply']}", flush=True)
