from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .maintenance_permissions import MaintenancePermission, allows
from .models import Role, User, UserStatus, Workspace
from .security import SESSION_COOKIE, decode_access_token

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)

WORKSPACE_NAMES = {
    Workspace.LOGISTICS: "Logistics Operations",
    Workspace.MAINTENANCE: "Maintenance Operations",
}


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
        token_version = int(payload.get("tv", 0))
        # Tokens issued before workspaces existed were logistics sessions.
        workspace = Workspace(payload.get("ws", Workspace.LOGISTICS.value))
    except jwt.PyJWTError, KeyError, ValueError, TypeError:
        raise _UNAUTHENTICATED from None
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise _UNAUTHENTICATED
    if token_version != user.token_version:  # signed out, password changed or access revoked
        raise _UNAUTHENTICATED
    request.state.workspace = workspace
    return user


def session_workspace(request: Request, _: User = Depends(get_current_user)) -> Workspace:
    """The workspace the current (already authenticated) session is bound to."""
    return request.state.workspace


def require_workspace(workspace: Workspace) -> Callable[..., User]:
    """Router-level guard: the session must be bound to `workspace`, and the account must
    still be allowed into it. A session for the other workspace gets 403 (not 401), so the
    client knows to ask for the password again rather than treat it as an expired session."""

    def dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if request.state.workspace is not workspace:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This session is signed in to {WORKSPACE_NAMES[request.state.workspace]}. "
                f"Sign in to {WORKSPACE_NAMES[workspace]} to continue.",
                headers={"X-Workspace-Required": workspace.value},
            )
        if not user.can_access(workspace):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Your account does not have access to {WORKSPACE_NAMES[workspace]}.",
            )
        return user

    return dependency


def revoke_sessions(user: User) -> None:
    """Invalidate every token issued to this user (takes effect on their next request)."""
    user.token_version = (user.token_version or 0) + 1


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


maintenance_user = require_workspace(Workspace.MAINTENANCE)


def require_maintenance(permission: MaintenancePermission) -> Callable[..., User]:
    """A maintenance-workspace session whose maintenance role grants `permission`."""

    def dependency(user: User = Depends(maintenance_user)) -> User:
        if not allows(user.effective_maintenance_role, permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You do not have permission for this action"
            )
        return user

    return dependency
