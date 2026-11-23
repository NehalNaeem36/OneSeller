from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..errors import AppError, bad_request
from ..models import Role, Store, User
from ..ratelimit import client_ip, limiter
from ..schemas import AuthOut, LoginIn, RegisterIn, UserOut
from ..security import create_token, get_current_user, hash_password, verify_password
from ..services import billing

router = APIRouter(prefix="/api/auth", tags=["auth"])


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "store"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    while db.scalar(select(Store.id).where(Store.slug == slug)):
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def _auth_out(db: Session, user: User) -> dict:
    store = db.scalars(select(Store).where(Store.owner_id == user.id)).first()
    return {"token": create_token(user), "user": UserOut.model_validate(user).model_dump(),
            "store_slug": store.slug if store else None}


@router.post("/register", response_model=AuthOut)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    limiter.hit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError(409, "email_taken", "An account with this email already exists")
    if body.role == "seller" and not (body.store_name and body.store_name.strip()):
        raise bad_request("Store name is required for seller accounts", code="store_name_required")
    try:
        user = User(email=email, password_hash=hash_password(body.password), role=Role(body.role),
                    full_name=body.full_name)
        db.add(user)
        db.flush()
        if user.role == Role.seller:
            # Atomic onboarding: user → store (unique storefront URL) → one-month free trial.
            store = Store(owner_id=user.id, name=body.store_name.strip(), slug=unique_slug(db, body.store_name),
                          tagline=f"Welcome to {body.store_name.strip()}")
            db.add(store)
            db.flush()
            billing.start_trial(db, store)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "email_taken", "An account with this email already exists")
    return _auth_out(db, user)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    limiter.hit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    user = db.scalars(select(User).where(User.email == body.email.lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise AppError(401, "invalid_credentials", "Incorrect email or password")
    return _auth_out(db, user)


@router.get("/me", response_model=AuthOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _auth_out(db, user)
