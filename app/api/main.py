from __future__ import annotations

from fastapi import FastAPI

from app.api.limits import RequestSizeLimitMiddleware
from app.api.routes import public_router, router

app = FastAPI(title="Invoice-to-Pay Agent", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(RequestSizeLimitMiddleware)
app.include_router(public_router)
app.include_router(router)
