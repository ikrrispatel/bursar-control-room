from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


MAX_REQUEST_BYTES = 50 * 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/runs":
            raw_length = request.headers.get("content-length")
            if raw_length:
                try:
                    if int(raw_length) > MAX_REQUEST_BYTES:
                        return JSONResponse(status_code=413, content={"detail": "request is too large"})
                except ValueError:
                    return JSONResponse(status_code=400, content={"detail": "invalid request length"})
        return await call_next(request)
