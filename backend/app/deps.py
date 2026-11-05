from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, User, UserStatus
from .security import SESSION_COOKIE, decode_access_token

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request) -> str | None:
    """Browser clients use the httpOnly session cookie; API clients may send a Bearer token."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise _UNAUTHENTICATED
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except jwt.PyJWTError, KeyError, ValueError:
        raise _UNAUTHENTICATED from None
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise _UNAUTHENTICATED
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """Dependency factory: allow only the given roles (administrators are always allowed)."""
    allowed = {Role.ADMIN, *roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You do not have permission for this action"
            )
        return user

    return dependency
