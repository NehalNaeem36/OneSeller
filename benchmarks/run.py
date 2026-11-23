"""OneSeller agent benchmark runner.

Starts a fresh, seeded API server as a subprocess (so 'restart' steps are real process restarts), drives the
public POST /chat API with the scenarios in tests.json / security_tests.json, verifies replies, tool calls,
tool arguments and database state, and reports success rate, tool accuracy, tokens, LLM calls, cost and latency.

Usage (from repo root):
  cd backend && uv run python ../benchmarks/run.py --provider ollama
  cd backend && uv run python ../benchmarks/run.py --provider anthropic --budget 1.00     # paid, guarded

Spending guard (anthropic): a persistent ledger (benchmarks/results/anthropic_ledger.json) accumulates real cost
across runs. The server is started with LLM_BUDGET_USD = cap - already_spent, and the server refuses any call
that would exceed it (checked before every call). The runner also stops early if remaining budget < --min-remaining.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks"
RESULTS = BENCH / "results"
BACKEND = ROOT / "backend"
LEDGER = RESULTS / "anthropic_ledger.json"
HARD_CAP_USD = 1.00          # user authorization: never more than $1 total for final API testing
SAFETY_FRACTION = 0.90       # server-side cap = 90% of the authorized amount (margin for estimation error)


# ---------------------------------------------------------------- server lifecycle

class Server:
    def __init__(self, provider: str, db_path: Path, port: int, budget_usd: float, model: str | None):
        self.port, self.proc = port, None
        self.env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}", "LLM_PROVIDER": provider,
                    "LLM_BUDGET_USD": f"{budget_usd:.6f}", "RATE_LIMIT_CHAT_PER_MINUTE": "1000",
                    "CORS_ORIGINS": "http://localhost:3000"}
        if model and provider == "ollama":
            self.env["OLLAMA_MODEL"] = model
        if model and provider == "anthropic":
            self.env["ANTHROPIC_MODEL"] = model
        self.log = open(RESULTS / "bench_server.log", "a")

    def setup_db(self) -> None:
        for cmd in (["uv", "run", "alembic", "upgrade", "head"], ["uv", "run", "python", "-m", "app.seed"]):
            subprocess.run(cmd, cwd=BACKEND, env=self.env, check=True, stdout=self.log, stderr=self.log)

    def start(self) -> None:
        self.proc = subprocess.Popen(["uv", "run", "uvicorn", "app.main:app", "--port", str(self.port)],
                                     cwd=BACKEND, env=self.env, stdout=self.log, stderr=self.log)
        for _ in range(120):
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1).text == "ok":
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError("server did not start; see benchmarks/results/bench_server.log")

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

    def restart(self) -> None:
        self.stop()
        self.start()


# ---------------------------------------------------------------- checks

def contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def check_turn(resp: dict, expect: dict) -> list[str]:
    errors = []
    reply = resp.get("reply", "")
    called = [c["name"] for c in resp.get("tool_calls", [])]
    if set(resp) != {"reply", "tool_calls", "tokens"} or set(resp.get("tokens", {})) != {"in", "out"}:
        errors.append(f"bad response schema: {sorted(resp)}")
    if (tools := expect.get("tools_any")) and not any(t in called for t in tools):
        errors.append(f"expected one of tools {tools}, got {called}")
    if (none := expect.get("tools_none")) is not None:
        bad = called if "*" in none else [t for t in called if t in none]
        if bad:
            errors.append(f"forbidden tools called: {bad}")
    for tool, constraints in (expect.get("tool_args") or {}).items():
        calls = [c for c in resp.get("tool_calls", []) if c["name"] == tool]
        if calls and not any(all(_arg_ok(c["args"].get(k), cons) for k, cons in constraints.items()) for c in calls):
            errors.append(f"{tool} args {[c['args'] for c in calls]} violate {constraints}")
    for n in expect.get("reply_all", []):
        if not contains(reply, n):
            errors.append(f"reply missing {n!r}")
    if (anyof := expect.get("reply_any")) and not any(contains(reply, n) for n in anyof):
        errors.append(f"reply has none of {anyof}")
    for n in expect.get("reply_none", []):
        if contains(reply, n):
            errors.append(f"reply must not contain {n!r}")
    return errors


def _arg_ok(value, cons: dict) -> bool:
    try:
        if "lte" in cons and not (value is not None and float(value) <= cons["lte"]):
            return False
        if "gte" in cons and not (value is not None and float(value) >= cons["gte"]):
            return False
        if "equals" in cons and str(value).lower() != str(cons["equals"]).lower():
            return False
    except (TypeError, ValueError):
        return False
    return True


def check_db(db_path: Path, principal: str, spec: dict) -> list[str]:
    con = sqlite3.connect(db_path)
    errors = []
    try:
        if "orders" in spec:
            n = con.execute("select count(*) from orders where principal=?", (principal,)).fetchone()[0]
            if n != spec["orders"]:
                errors.append(f"expected {spec['orders']} orders in DB, found {n}")
        if "cart_items" in spec:
            n = con.execute("select coalesce(sum(ci.quantity),0) from cart_items ci join carts c on c.id=ci.cart_id "
                            "where c.principal=?", (principal,)).fetchone()[0]
            if n != spec["cart_items"]:
                errors.append(f"expected {spec['cart_items']} cart items in DB, found {n}")
        if "order_quantity" in spec:
            n = con.execute("select coalesce(sum(oi.quantity),0) from order_items oi join orders o on o.id=oi.order_id "
                            "where o.principal=?", (principal,)).fetchone()[0]
            if n != spec["order_quantity"]:
                errors.append(f"expected {spec['order_quantity']} units ordered, found {n}")
        if "product_price" in spec:
            p = spec["product_price"]
            row = con.execute("select price from products where name=?", (p["name"],)).fetchone()
            if not row or float(row[0]) != float(p["equals"]):
                errors.append(f"price of {p['name']} changed: {row}")
    finally:
        con.close()
    return errors


def usage_totals(db_path: Path) -> dict:
    con = sqlite3.connect(db_path)
    try:
        r = con.execute("select count(*), coalesce(sum(tokens_in),0), coalesce(sum(tokens_out),0), "
                        "coalesce(sum(cost_usd),0) from usage_log").fetchone()
    finally:
        con.close()
    return {"llm_calls": r[0], "tokens_in": r[1], "tokens_out": r[2], "cost_usd": round(r[3], 6)}


# ---------------------------------------------------------------- ledger

def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"authorized_usd": HARD_CAP_USD, "total_usd": 0.0, "runs": []}


def save_ledger(ledger: dict) -> None:
    LEDGER.write_text(json.dumps(ledger, indent=2))


# ---------------------------------------------------------------- main

def run_suite(path: Path, server: Server, db_path: Path, client: httpx.Client, run_id: str, only: set[str] | None,
              min_remaining: float, cap: float, prior: float) -> list[dict]:
    suite = json.loads(path.read_text())
    out = []
    for case in suite["cases"]:
        if only and case["id"] not in only:
            continue
        if server.env["LLM_PROVIDER"] == "anthropic":
            spent = prior + usage_totals(db_path)["cost_usd"]
            if cap - spent < min_remaining:
                print(f"!! stopping: remaining budget ${cap - spent:.4f} < ${min_remaining}")
                break
        users: dict[str, str] = {}
        turns, errors = [], []
        t_case = time.perf_counter()
        for i, step in enumerate(case["steps"]):
            user = users.setdefault(step.get("user", "main"), f"{run_id}-{case['id']}-{step.get('user', 'main')}")
            if step.get("restart"):
                server.restart()
                turns.append({"step": i, "restart": True})
                continue
            if "check_db" in step:
                errs = check_db(db_path, f"api:{user}", step["check_db"])
                errors += [f"step {i}: {e}" for e in errs]
                turns.append({"step": i, "check_db": step["check_db"], "ok": not errs})
                continue
            thread = f"{case['id']}-{step.get('thread', 'main')}"
            if step.get("user") == "attacker" and step.get("thread") == "shared":
                thread = f"{case['id']}-shared"   # same thread_id as the victim
            if step.get("user") == "victim":
                thread = f"{case['id']}-shared"
            t0 = time.perf_counter()
            try:
                r = client.post(f"http://127.0.0.1:{server.port}/chat",
                                json={"user_id": user, "thread_id": thread, "message": step["message"]})
                resp = r.json() if r.status_code == 200 else {"reply": f"HTTP {r.status_code}", "tool_calls": [], "tokens": {"in": 0, "out": 0}}
            except httpx.HTTPError as exc:
                resp = {"reply": f"request failed: {exc}", "tool_calls": [], "tokens": {"in": 0, "out": 0}}
            latency = time.perf_counter() - t0
            errs = check_turn(resp, step.get("expect", {})) if "expect" in step else []
            errors += [f"step {i}: {e}" for e in errs]
            tool_expect = any(k in step.get("expect", {}) for k in ("tools_any", "tools_none", "tool_args"))
            tool_ok = tool_expect and not any(e.startswith(("expected one of tools", "forbidden tools")) or " args " in e for e in errs)
            turns.append({"step": i, "message": step["message"], "reply": resp.get("reply", ""),
                          "tool_calls": resp.get("tool_calls", []), "tokens": resp.get("tokens", {}),
                          "latency_s": round(latency, 2), "errors": errs,
                          "tool_check": (tool_ok if tool_expect else None)})
            mark = "✓" if not errs else "✗"
            print(f"  {case['id']} step {i} {mark} {latency:5.1f}s tools={[c['name'] for c in resp.get('tool_calls', [])]} "
                  f"tok={resp.get('tokens')}" + (f"  {errs}" if errs else ""))
        out.append({"id": case["id"], "category": case["category"], "title": case["title"], "passed": not errors,
                    "errors": errors, "turns": turns, "seconds": round(time.perf_counter() - t_case, 1)})
        print(f"{'PASS' if not errors else 'FAIL'} {case['id']} {case['title']}")
    return out


def summarize(cases: list[dict]) -> dict:
    chat_turns = [t for c in cases for t in c["turns"] if "message" in t]
    tool_turns = [t for t in chat_turns if t["tool_check"] is not None]
    lat = [t["latency_s"] for t in chat_turns]
    return {
        "cases": len(cases), "passed": sum(c["passed"] for c in cases),
        "success_rate": round(100 * sum(c["passed"] for c in cases) / len(cases), 1) if cases else 0,
        "turns": len(chat_turns),
        "tool_accuracy": round(100 * sum(t["tool_check"] for t in tool_turns) / len(tool_turns), 1) if tool_turns else None,
        "tokens_in": sum(t["tokens"].get("in", 0) for t in chat_turns),
        "tokens_out": sum(t["tokens"].get("out", 0) for t in chat_turns),
        "avg_latency_s": round(sum(lat) / len(lat), 2) if lat else 0,
        "max_latency_s": max(lat) if lat else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["ollama", "anthropic"], default="ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("--suite", choices=["functional", "security", "all"], default="all")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--budget", type=float, default=HARD_CAP_USD, help="anthropic: total authorized USD (<= 1.00)")
    ap.add_argument("--min-remaining", type=float, default=0.05)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    cap = min(a.budget, HARD_CAP_USD) * SAFETY_FRACTION
    ledger = load_ledger()
    prior = ledger["total_usd"] if a.provider == "anthropic" else 0.0
    server_budget = max(0.0, cap - prior) if a.provider == "anthropic" else 0.90
    if a.provider == "anthropic":
        print(f"Budget: authorized ${min(a.budget, HARD_CAP_USD):.2f}, enforced cap ${cap:.2f}, already spent ${prior:.4f}, "
              f"remaining ${server_budget:.4f}")
        if server_budget < a.min_remaining:
            print("Refusing to run: insufficient remaining budget.")
            return 2

    run_id = f"{a.provider[:3]}{datetime.now().strftime('%m%d%H%M%S')}{uuid.uuid4().hex[:3]}"
    db_path = RESULTS / f"bench_{run_id}.db"
    server = Server(a.provider, db_path, a.port, server_budget, a.model)
    server.setup_db()
    server.start()
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    client = httpx.Client(timeout=300)
    results: dict = {"run_id": run_id, "provider": a.provider,
                     "model": a.model or ("claude-haiku-5-5" if a.provider == "anthropic" else "qwen3:4b-instruct-2507-q4_K_M"),
                     "started_at": datetime.now(timezone.utc).isoformat(), "label": a.label, "suites": {}}
    try:
        suites = ["functional", "security"] if a.suite == "all" else [a.suite]
        for name in suites:
            path = BENCH / ("tests.json" if name == "functional" else "security_tests.json")
            print(f"\n=== {name} ({path.name}) ===")
            cases = run_suite(path, server, db_path, client, run_id, only, a.min_remaining, cap, prior)
            results["suites"][name] = {"summary": summarize(cases), "cases": cases}
    finally:
        server.stop()
        usage = usage_totals(db_path)
        results["usage"] = usage
        if a.provider == "anthropic":
            ledger["total_usd"] = round(ledger["total_usd"] + usage["cost_usd"], 6)
            ledger["runs"].append({"run_id": run_id, "at": results["started_at"], "label": a.label, **usage})
            save_ledger(ledger)
            results["ledger_total_usd"] = ledger["total_usd"]
        out = RESULTS / f"{run_id}.json"
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        for p in (db_path, Path(str(db_path).replace(".db", "_checkpoints.db"))):
            for suffix in ("", "-wal", "-shm"):
                Path(str(p) + suffix).unlink(missing_ok=True)

    print("\n=== Summary ===")
    for name, s in results["suites"].items():
        print(f"{name:10s} {json.dumps(s['summary'])}")
    print(f"usage      {json.dumps(usage)}" + (f"  ledger_total=${results.get('ledger_total_usd')}" if a.provider == "anthropic" else ""))
    print(f"saved      {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
