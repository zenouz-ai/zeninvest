"""Operator authentication router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.utils.config import get_settings

from ..schemas import AuthLoginRequestSchema, AuthSessionSchema
from ..services.auth import (
    SESSION_COOKIE_NAME,
    auth_me_payload,
    authenticate_operator,
    create_session_token,
    current_operator_session,
    decode_session_token,
    is_secure_request,
    operator_transport_allowed,
)

router = APIRouter()
settings = get_settings()


@router.post("/login", response_model=AuthSessionSchema)
async def login_operator(payload: AuthLoginRequestSchema, request: Request, response: Response):
    """Authenticate an operator and issue a signed session cookie."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")
    if not operator_transport_allowed(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Operator login requires HTTPS. For local development, set "
                "DASHBOARD_INSECURE_DEV_MODE=true and use localhost only."
            ),
        )
    if not authenticate_operator(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_session_token(payload.username)
    secure_cookie = is_secure_request(request) or not settings.dashboard_insecure_dev_mode
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    session = decode_session_token(token)
    return AuthSessionSchema(
        authenticated=True,
        username=payload.username,
        expires_at=session.expires_at if session else None,
    )


@router.post("/logout", response_model=AuthSessionSchema)
async def logout_operator(response: Response):
    """Clear the operator session cookie."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="lax")
    return AuthSessionSchema(authenticated=False, username=None, expires_at=None)


@router.get("/me", response_model=AuthSessionSchema)
async def get_current_operator(request: Request):
    """Return the current operator session status."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")
    session = current_operator_session(request)
    return AuthSessionSchema(**auth_me_payload(session))
