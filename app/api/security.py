from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class APIPrincipal:
    actor_id: str
    is_finance_reviewer: bool


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="API authentication failed", headers={"WWW-Authenticate": "Bearer"})


def require_api_auth(request: Request) -> APIPrincipal:
    mode = os.getenv("BURSAR_API_AUTH_MODE", "required").strip().lower()
    if mode == "local":
        return APIPrincipal(
            actor_id=os.getenv("BURSAR_LOCAL_FINANCE_REVIEWER_ID", "local-finance-reviewer"),
            is_finance_reviewer=True,
        )
    if mode != "required":
        raise HTTPException(status_code=503, detail="API authentication mode is invalid")

    reviewer_key = os.getenv("BURSAR_FINANCE_REVIEWER_API_KEY")
    api_key = os.getenv("BURSAR_API_KEY")
    if not reviewer_key and not api_key:
        raise HTTPException(status_code=503, detail="API authentication is not configured")

    authorization = request.headers.get("authorization", "")
    presented = authorization[7:].strip() if authorization.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    if not presented:
        raise _unauthorized()

    if reviewer_key and secrets.compare_digest(presented, reviewer_key):
        reviewer_id = os.getenv("BURSAR_FINANCE_REVIEWER_ID")
        if not reviewer_id:
            raise HTTPException(status_code=503, detail="finance reviewer authentication is not configured")
        return APIPrincipal(actor_id=reviewer_id, is_finance_reviewer=True)
    if api_key and secrets.compare_digest(presented, api_key):
        return APIPrincipal(actor_id="authenticated-api-client", is_finance_reviewer=False)
    raise _unauthorized()


def require_finance_reviewer(request: Request) -> APIPrincipal:
    principal = require_api_auth(request)
    if not principal.is_finance_reviewer:
        raise HTTPException(status_code=403, detail="finance reviewer authorization is required")
    return principal
