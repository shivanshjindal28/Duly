"""FastAPI application factory: middleware, security headers and routers."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api import (about, admin, approvals, audit, auth, bank_changes, chat, dashboard, health, impact, invoices, payments,
                     portal, reports, stores, suppliers)
from app.core.config import get_settings
from app.core import clock, runtime
from app.core.db import SessionLocal, create_all
from app.core.ratelimit import limiter

_DOCS_PATHS = ("/api/docs", "/api/openapi.json")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Duly API",
        version=__version__,
        description="Smart procure-to-pay assistant for Plant X (fictional).",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith(_DOCS_PATHS):
            # The API serves JSON only; Swagger UI (dev docs) needs its CDN assets.
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(invoices.router, prefix="/api")
    app.include_router(suppliers.router, prefix="/api")
    app.include_router(stores.router, prefix="/api")
    app.include_router(approvals.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(portal.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(bank_changes.router, prefix="/api")
    app.include_router(payments.router, prefix="/api")
    app.include_router(impact.router, prefix="/api")
    app.include_router(about.router, prefix="/api")
    return app


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_all()
    db = SessionLocal()
    try:
        clock.load_offset(db)  # demo clock offset survives restarts
        runtime.load_ai_mode(db)  # so does the admin's AI mode switch
    finally:
        db.close()
    yield


app = create_app()
