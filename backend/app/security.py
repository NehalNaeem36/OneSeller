from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import AppError
from .models import Role, Store, User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "role": user.role.value, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_expire_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def _unauthorized(msg: str = "Authentication required") -> AppError:
    return AppError(401, "unauthorized", msg)


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired, please log in again")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")
    user = db.get(User, int(payload.get("sub", 0) or 0))
    if not user:
        raise _unauthorized("Account no longer exists")
    return user


def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.customer:
        raise AppError(403, "forbidden", "Customer account required")
    return user


def require_seller(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.seller:
        raise AppError(403, "forbidden", "Seller account required")
    return user


def current_store(user: User = Depends(require_seller), db: Session = Depends(get_db)) -> Store:
    """Tenant scope for every seller endpoint: always derived from the JWT, never from input."""
    store = db.query(Store).filter(Store.owner_id == user.id).one_or_none()
    if not store:
        raise AppError(404, "not_found", "Store not found for this seller")
    return store


def customer_principal(user: User) -> str:
    return f"user:{user.id}"
