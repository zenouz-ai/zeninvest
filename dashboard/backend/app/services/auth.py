"""Dashboard operator authentication helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from src.utils.config import get_settings

settings = get_settings()

SESSION_COOKIE_NAME = "dashboard_operator_session"
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_DELIMITER = ":"


class DashboardAuthConfigError(RuntimeError):
    """Raised when dashboard auth configuration is incomplete or invalid."""


@dataclass(frozen=True)
class OperatorSession:
    """Decoded operator session payload."""

    username: str
    expires_at: int


def b64url_encode(raw: bytes) -> str:
    """Encode bytes using base64url without padding."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    """Decode base64url bytes with optional padding stripped."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = 600_000, salt: str | None = None) -> str:
    """Return a PBKDF2-SHA256 hash string for the supplied password."""
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        iterations,
    )
    return PBKDF2_DELIMITER.join([PBKDF2_PREFIX, str(iterations), salt_value, digest.hex()])


def verify_password(password: str, password_hash: str) -> bool:
    """Validate a password against a PBKDF2-SHA256 hash string."""
    try:
        prefix, iteration_raw, salt, expected_hex = password_hash.split(PBKDF2_DELIMITER, 3)
        if prefix != PBKDF2_PREFIX:
            return False
        iterations = int(iteration_raw)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual, expected_hex)


def validate_password_hash_format(password_hash: str | None) -> bool:
    """Return True when the configured password hash looks valid."""
    if not password_hash:
        return False
    parts = password_hash.split(PBKDF2_DELIMITER, 3)
    if len(parts) != 4 or parts[0] != PBKDF2_PREFIX:
        return False
    try:
        int(parts[1])
    except ValueError:
        return False
    return bool(parts[2]) and bool(parts[3])


def create_session_token(username: str, *, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> str:
    """Create a signed operator session token."""
    secret = settings.dashboard_session_secret
    if not secret:
        raise DashboardAuthConfigError("DASHBOARD_SESSION_SECRET is not configured")
    payload = {
        "sub": username,
        "exp": int(time.time()) + ttl_seconds,
        "iat": int(time.time()),
    }
    payload_b64 = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def decode_session_token(token: str | None) -> OperatorSession | None:
    """Validate and decode an operator session token."""
    secret = settings.dashboard_session_secret
    if not token or not secret:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    try:
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    username = payload.get("sub")
    expires_at = payload.get("exp")
    if not isinstance(username, str) or not isinstance(expires_at, int):
        return None
    if expires_at <= int(time.time()):
        return None
    return OperatorSession(username=username, expires_at=expires_at)


def is_localhost_request(request: Request) -> bool:
    """Return True when the request targets localhost for dev-only login."""
    hostname = (request.url.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1"}:
        return True
    client_host = (request.client.host if request.client else "").lower()
    return client_host in {"127.0.0.1", "::1"}


def is_secure_request(request: Request) -> bool:
    """Return True when the request arrived over HTTPS or trusted proxy HTTPS."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def operator_transport_allowed(request: Request) -> bool:
    """Allow operator login/session only on HTTPS, except localhost dev mode."""
    if is_secure_request(request):
        return True
    return settings.dashboard_insecure_dev_mode and is_localhost_request(request)


def require_dashboard_auth_config() -> None:
    """Fail closed when dashboard operator auth configuration is incomplete."""
    missing: list[str] = []
    if not settings.dashboard_operator_username:
        missing.append("DASHBOARD_OPERATOR_USERNAME")
    if not settings.dashboard_operator_password_hash:
        missing.append("DASHBOARD_OPERATOR_PASSWORD_HASH")
    if not settings.dashboard_session_secret:
        missing.append("DASHBOARD_SESSION_SECRET")
    if missing:
        raise DashboardAuthConfigError(
            "Dashboard auth is not configured. Missing env vars: " + ", ".join(missing)
        )
    if not validate_password_hash_format(settings.dashboard_operator_password_hash):
        raise DashboardAuthConfigError(
            "DASHBOARD_OPERATOR_PASSWORD_HASH must use pbkdf2_sha256:iterations:salt:hash format"
        )


def authenticate_operator(username: str, password: str) -> bool:
    """Validate operator credentials against configured env-backed secrets."""
    configured_username = settings.dashboard_operator_username
    configured_hash = settings.dashboard_operator_password_hash
    if not configured_username or not configured_hash:
        return False
    if not hmac.compare_digest(username, configured_username):
        return False
    return verify_password(password, configured_hash)


def current_operator_session(request: Request) -> OperatorSession | None:
    """Return the current operator session, if present and valid."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return decode_session_token(token)


def auth_me_payload(session: OperatorSession | None) -> dict[str, Any]:
    """Serialize the operator session for /api/auth/me."""
    if not session:
        return {"authenticated": False, "username": None}
    return {
        "authenticated": True,
        "username": session.username,
        "expires_at": session.expires_at,
    }
