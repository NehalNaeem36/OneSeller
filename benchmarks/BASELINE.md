# Phase 1 — Baseline test results

Date: 2026-11-23 · Machine: 16-core CPU, 14 GB RAM, RTX 3050 Laptop (4 GB) · LLM: `qwen3:4b-instruct-2507-q4_K_M` via Ollama 0.40.3 (local, $0).
No paid API calls were made in Phase 1.

These are baseline checks, not the Phase 2 benchmark. The `tests.json` functional suite and the separate security suite will be built and run in Phase 2.

## 1. Automated tests — `backend/tests` (pytest)

**33 / 33 passed** (~14 s, no network: the agent tests use a scripted fake LLM).

| Area | Tests cover |
|---|---|
| Accounts | Seller signup creates store + unique slug + 1-month trial; validation; duplicate email; login; role guards; forged token |
| Seller isolation | Seller B gets 404 on seller A's product read/update/delete/restore/bulk, orders, status updates; dashboard KPIs scoped; foreign image ids rejected |
| Customer isolation | Separate carts; other customers' orders return 404 |
| Catalog | Combined filters (keywords + color + size + max price, category, in-stock, store, sort) |
| Deletion integrity | Soft delete hides + restore; hard delete needs `confirm=true`, refused while order is open, allowed after delivery; order keeps name/price snapshot |
| Bulk / import | Bulk stock/price/delete; CSV with bad rows (per-row errors, valid rows still imported), SKU upsert, XLSX import, missing columns, bad file type |
| Checkout | Explicit confirmation required; split per store; stock decremented; full rollback if any line fails; idempotent replay; **6 concurrent buyers for 3 units → exactly 3 orders, stock 0**; cancel restores stock; invalid transitions rejected |
| Subscriptions | Simulated expiry → product creation 402, products hidden, checkout refused; mock payment reactivates; premium placement; renewal extends period; monthly order limit enforced |
| Agent graph | Spec demo flow; persistence across graph rebuild (restart); confirmation gate vs rogue model; per-agent tool scope; 5 attack prompts blocked with 0 LLM calls; thread isolation between users; long-term memory across threads + restart, not shared across users; public API can't touch a real customer's cart; authenticated chat uses real cart/profile and decrements stock; declining the summary places no order; LLM failure still returns the `/chat` schema; budget guard blocks paid calls |

## 2. Live agent runs on local Qwen

### Spec demo conversation (`scripts/smoke_demo.py`, public `/chat`)

First run (before fixes) — `benchmarks/results/smoke_qwen_instruct.txt`:

| Turn | Result |
|---|---|
| Show me black shirts under Rs. 3000 in medium size | ✅ `search_products(query=shirt, color=black, size=M, max_price=3000)` |
| Which one is cheaper? | ✅ answered from short-term memory |
| Add the cheaper one to my cart | ✅ `add_to_cart` with the cheapest product id |
| I want to checkout | ⚠️ no tool call; LLM asked for details itself |
| (delivery details) | ⚠️ `set_delivery_details` but no `prepare_checkout`; LLM wrote its own summary |
| yes | ❌ **hallucinated "order confirmed, Order ID #ORD-12345" — no order existed** |

Fix (deterministic, not prompt-only): checkout intent → `prepare_checkout` in code; complete delivery details → `prepare_checkout` chained; `finalize` replaces any order-placed claim without a successful `create_order`. Regression tests added.

Second run (after fixes) — `benchmarks/results/smoke_qwen_instruct_v2.txt`: **6 / 6 turns correct**; real order #1 created only after "yes". Checkout + confirmation turns used 0 LLM tokens.

### Full HTTP end-to-end (`scripts/http_e2e.py`, real servers)

**13 / 13 checks passed:** health → seller signup with trial → storefront customization → CSV import (3 products) → marketplace search → customer chat search → comparison from memory → add cheaper item to real cart → confirmation summary → order after "yes" → stock decremented → seller sees order with delivery details → long-term memory saved → new thread recalls preference.

| Turn | Tools | Tokens in / out | Latency |
|---|---|---|---|
| search (+ "I usually wear size M") | `search_products` | 2205 / 202 | 10.1 s |
| Which one is cheaper? | — | 1226 / 51 | 3.1 s |
| Add the cheaper one to my cart | `add_to_cart` | 2934 / 85 | 5.3 s |
| checkout | `prepare_checkout` (deterministic) | 0 / 0 | 0.1 s |
| yes | `create_order` (deterministic) | 0 / 0 | 0.1 s |
| What size do I usually wear? (new thread) | — | 899 / 9 | 1.2 s |

Bug found in this run: the question "What size **do** I usually wear?" was parsed as size "DO" and saved. Fixed (sizes must be real size tokens; questions are never stored as preferences) with a regression test.

## 3. Frontend

`npm run build` succeeds (Next.js 15.5.4, type-checked, 19 routes). With `next start`, every main route returned HTTP 200 (`/`, `/search`, `/stores`, `/store/[slug]`, `/product/[id]`, `/login`, `/register`, `/cart`, `/seller`, `/seller/billing`), and the backend's CORS preflight allowed the frontend origin. The pages are client-rendered against the API, so their runtime behavior is covered by the HTTP E2E above. A click-through of the UI in a real browser has **not** been done yet.

## 4. Backend container

`docker build` of `backend/Dockerfile` succeeds; the container runs Alembic migrations on start and `GET /health` returns `ok` (port 7860, HF Spaces convention).

## 5. Issues found during development (and fixed)

| Issue | Cause | Fix |
|---|---|---|
| Agent produced no tool calls; output was plain-text "thinking" hitting the token cap | Installed `qwen3:4b` is a thinking build; `think=false` ignored (≈1,250 reasoning tokens / 35 s per step when thinking) | Switched to `qwen3:4b-instruct-2507` |
| Hallucinated order confirmation | Checkout relied on the LLM choosing `prepare_checkout` | Deterministic checkout path + output guard |
| Size saved as "m" in memory | Lower-casing list memories | Sizes stored upper-case |
| "DO" stored as a size | Over-broad size regex + questions treated as preferences | Strict size tokens; skip questions |

## Known limitations at baseline
- Phase 2 benchmark suite (`tests.json`, security suite, restart-between-conversations cases) still to be built; no success-rate claim yet.
- "Black shirts" also matches "T-Shirt" products (substring match on "shirt"). Arguably acceptable; to be reviewed against the benchmark.
- Rate limiter is in-process (fine for a single instance).
