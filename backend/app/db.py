from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


log = logging.getLogger("oneseller.db")


class Base(DeclarativeBase):
    pass


def sqlalchemy_url(url: str) -> str:
    """Normalize postgres URLs to the psycopg 3 driver SQLAlchemy should use."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _make_engine(url: str):
    url = sqlalchemy_url(url)
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # enforce FKs + better concurrency in SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return eng
    # Neon pooled endpoint (PgBouncer, transaction mode): no server-side prepared statements; pre-ping +
    # recycle because Neon computes scale to zero and drop idle connections.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5,
                         connect_args={"prepare_threshold": None})


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def reset_engine(url: str) -> None:
    """Used by tests to point the app at an isolated database."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:  # connection dropped by the server (e.g. Neon idle timeout): discard it, don't crash
            log.warning("discarding broken DB connection on session close", exc_info=True)
            try:
                db.invalidate()
            except Exception:
                pass
