"""Token / cost ledger and the hard spending guard for paid LLM providers."""
from __future__ import annotations

from sqlalchemy import func, select

from ..config import get_settings
from ..db import SessionLocal
from ..errors import AppError
from ..models import UsageLog


def cost_usd(provider: str, tokens_in: int, tokens_out: int) -> float:
    if provider != "anthropic":
        return 0.0
    s = get_settings()
    return (tokens_in * s.anthropic_price_in_per_mtok + tokens_out * s.anthropic_price_out_per_mtok) / 1_000_000


def total_spent(provider: str = "anthropic") -> float:
    with SessionLocal() as db:
        return float(db.scalar(select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0))
                               .where(UsageLog.provider == provider)) or 0.0)


def summary() -> dict:
    with SessionLocal() as db:
        rows = db.execute(select(UsageLog.provider, func.count(UsageLog.id), func.sum(UsageLog.tokens_in),
                                 func.sum(UsageLog.tokens_out), func.sum(UsageLog.cost_usd))
                          .group_by(UsageLog.provider)).all()
    return {p: {"calls": c, "tokens_in": int(i or 0), "tokens_out": int(o or 0), "cost_usd": round(float(k or 0), 6)}
            for p, c, i, o, k in rows}


class BudgetExceeded(AppError):
    def __init__(self):
        super().__init__(503, "budget_exhausted", "The AI assistant is temporarily unavailable (budget limit reached).")


def check_budget(provider: str) -> None:
    """Refuse the call if spent + per-call reserve would exceed the configured hard cap."""
    if provider != "anthropic":
        return
    s = get_settings()
    if total_spent("anthropic") + s.llm_budget_reserve_usd > s.llm_budget_usd:
        raise BudgetExceeded()


def record(provider: str, model: str, tokens_in: int, tokens_out: int, principal: str | None) -> float:
    c = cost_usd(provider, tokens_in, tokens_out)
    with SessionLocal() as db:
        db.add(UsageLog(provider=provider, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                        cost_usd=c, principal=principal))
        db.commit()
    return c
