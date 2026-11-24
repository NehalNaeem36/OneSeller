"""Authenticated agent chat used by the website (real cart, real orders, saved delivery details)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.runner import run_turn, thread_messages
from ..config import get_settings
from ..db import get_db
from ..errors import not_found
from ..models import ChatThread, User
from ..ratelimit import limiter
from ..schemas import AuthChatIn
from ..security import customer_principal, require_customer

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
def chat(body: AuthChatIn, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    limiter.hit(f"authchat:{user.id}", get_settings().rate_limit_chat_per_minute)
    # Return the auth lookup's connection to the pool now: an agent turn can take many seconds, and holding an
    # idle-in-transaction connection that long ties up the pool (and Neon may drop it).
    db.close()
    return run_turn(customer_principal(user), body.thread_id, body.message, channel="agent", sandbox=False,
                    customer_id=user.id)


@router.get("/threads")
def threads(user: User = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(ChatThread).where(ChatThread.principal == customer_principal(user))
                      .order_by(ChatThread.updated_at.desc()).limit(30))
    return [{"thread_id": r.thread_id, "title": r.title, "updated_at": r.updated_at.isoformat()} for r in rows]


@router.get("/threads/{thread_id}")
def thread(thread_id: str, user: User = Depends(require_customer), db: Session = Depends(get_db)):
    principal = customer_principal(user)
    if not db.scalar(select(ChatThread.id).where(ChatThread.principal == principal, ChatThread.thread_id == thread_id)):
        raise not_found("Conversation")
    return {"thread_id": thread_id, "messages": thread_messages(principal, thread_id)}
