from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from .config import get_settings
from .errors import AppError
from .routers import auth, chat, customer, marketplace, public, seller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("oneseller")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="OneSeller AI API", version="0.1.0",
                  description="Marketplace + LangGraph AI sales agent. Public grading endpoints: POST /chat, GET /health.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_origin_regex=r"https://.*\.vercel\.app",
                       allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        rid = uuid.uuid4().hex[:10]
        request.state.rid = rid
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t0) * 1000, rid)
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": exc.message, **exc.extra}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error",
                                                                "message": "Invalid request", "details": details}})

    @app.exception_handler(OperationalError)
    async def db_down(request: Request, exc: OperationalError):
        log.exception("database error rid=%s", getattr(request.state, "rid", "-"))
        return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable",
                                                                "message": "Service temporarily unavailable, please retry."}})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "rid", "-")
        log.exception("unhandled error rid=%s", rid)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error",
                                                                "message": f"Something went wrong (ref {rid})."}})

    for r in (public.router, auth.router, marketplace.router, customer.router, seller.router, chat.router):
        app.include_router(r)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": s.app_name, "docs": "/docs", "health": "/health", "chat": "POST /chat"}

    return app


app = create_app()
