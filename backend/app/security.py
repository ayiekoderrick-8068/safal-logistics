from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from .config import get_settings

SESSION_COOKIE = "logitrack_session"
# bcrypt only considers the first 72 bytes; longer passwords are rejected at validation.
MAX_PASSWORD_BYTES = 72


def validate_password(password: str) -> str | None:
    """Password policy shared by the CLI, self-service change and administrator resets."""
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
    if not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        return "Password must contain letters and numbers."
    if all(c.isalnum() for c in password):
        return "Password must contain at least one symbol."
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# Used to keep login timing constant when the username does not exist.
_DUMMY_HASH = bcrypt.hashpw(b"logitrack-timing-equaliser", bcrypt.gensalt(rounds=12)).decode()


def verify_against_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(
    user_id: int, role: str, token_version: int = 0, workspace: str = "logistics"
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "tv": token_version,  # must equal users.token_version, or the session is revoked
        "ws": workspace,  # the one workspace this session may use
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "iat"]},
    )
