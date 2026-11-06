from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import WORKSPACE_NAMES, get_current_user, revoke_sessions, session_workspace
from ..models import User, UserStatus, Workspace
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    SessionUserOut,
    SwitchWorkspaceRequest,
    UserOut,
)
from ..security import (
    SESSION_COOKIE,
    create_access_token,
    hash_password,
    validate_password,
    verify_against_dummy,
    verify_password,
)
from ..services import throttle

router = APIRouter(prefix="/api/auth", tags=["auth"])

# One message for unknown users and wrong passwords, so usernames cannot be enumerated.
INVALID_MESSAGE = "Invalid username or password"
LOCKED_MESSAGE = (
    "Too many sign-in attempts. For your security, sign-in is paused — try again later "
    "or contact an administrator."
)


def _locked(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, LOCKED_MESSAGE, headers={"Retry-After": str(retry_after)}
    )


def _no_access(workspace: Workspace) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Your account does not have access to {WORKSPACE_NAMES[workspace]}. "
        "Ask an administrator to grant it.",
    )


def _session_user(user: User, workspace: Workspace) -> SessionUserOut:
    return SessionUserOut(**UserOut.model_validate(user).model_dump(), workspace=workspace)


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> LoginResponse:
    identifier = body.username.strip().lower()
    acct = throttle.account_key(identifier)
    ip = throttle.ip_key(request.client.host if request.client else None)
    keys = [k for k in (acct, ip) if k]

    # Refuse while locked - before touching the password, and for real or unknown accounts alike.
    if lock := throttle.check(db, keys):
        verify_against_dummy(body.password)  # keep timing uniform
        record_event(
            db,
            action="auth.login_throttled",
            entity_type="user",
            summary="Sign-in refused: too many failed attempts",
            request=request,
        )
        db.commit()
        raise _locked(lock.retry_after_seconds)

    user = db.scalar(
        select(User).where(
            or_(func.lower(User.username) == identifier, func.lower(User.email) == identifier)
        )
    )
    if user is not None:
        valid = verify_password(body.password, user.password_hash)
    else:
        verify_against_dummy(body.password)  # same cost as a real check
        valid = False

    if not valid or user is None:
        triggered = throttle.register_failure(db, acct, ip)
        record_event(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            summary=f"Failed login for {user.username}"
            if user
            else "Failed login for unknown user",
            request=request,
        )
        if triggered:
            record_event(
                db,
                action="auth.locked",
                entity_type="user",
                entity_id=user.id if user else None,
                summary="Sign-in locked after repeated failures",
                request=request,
                changes={"retry_after_seconds": triggered.retry_after_seconds},
            )
        db.commit()
        if triggered:
            raise _locked(triggered.retry_after_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_MESSAGE)

    if user.status != UserStatus.ACTIVE:
        # Only reachable with the correct password, so this does not aid enumeration.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is not active")

    throttle.register_success(db, acct)
    if not user.can_access(body.workspace):
        # Also only reachable with the correct password. Refused before any session is issued.
        record_event(
            db,
            action="auth.workspace_denied",
            entity_type="user",
            entity_id=user.id,
            actor=user,
            summary=f"{user.username} has no access to {WORKSPACE_NAMES[body.workspace]}",
            request=request,
            changes={"workspace": body.workspace.value},
        )
        db.commit()
        raise _no_access(body.workspace)

    user.last_login_at = datetime.now(UTC)
    record_event(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        summary=f"{user.username} signed in to {WORKSPACE_NAMES[body.workspace]}",
        request=request,
        changes={"workspace": body.workspace.value},
    )
    db.commit()
    max_age = _set_session_cookie(response, user, body.workspace)
    return LoginResponse(user=_session_user(user, body.workspace), expires_in_seconds=max_age)


@router.post("/switch-workspace", response_model=LoginResponse)
def switch_workspace(
    body: SwitchWorkspaceRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    current: Workspace = Depends(session_workspace),
) -> LoginResponse:
    """Move this session to the other workspace. Always requires the password again, with
    the same lockout as sign-in; on success the old session token is replaced."""
    acct = throttle.account_key(user.username)
    if lock := throttle.check(db, [acct]):
        raise _locked(lock.retry_after_seconds)
    if body.workspace is current:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"You are already in {WORKSPACE_NAMES[current]}."
        )
    if not verify_password(body.password, user.password_hash):
        triggered = throttle.register_failure(db, acct, None)
        record_event(
            db,
            action="auth.workspace_switch_failed",
            entity_type="user",
            entity_id=user.id,
            actor=user,
            summary="Workspace switch refused: password incorrect",
            request=request,
            changes={"from": current.value, "to": body.workspace.value},
        )
        db.commit()
        if triggered:
            raise _locked(triggered.retry_after_seconds)
        # 400, not 401: the session itself is still valid.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The password is incorrect.")
    throttle.register_success(db, acct)
    if not user.can_access(body.workspace):
        db.commit()
        raise _no_access(body.workspace)
    record_event(
        db,
        action="auth.workspace_switched",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        summary=f"{user.username} switched to {WORKSPACE_NAMES[body.workspace]}",
        request=request,
        changes={"from": current.value, "to": body.workspace.value},
    )
    db.commit()
    max_age = _set_session_cookie(response, user, body.workspace)
    return LoginResponse(user=_session_user(user, body.workspace), expires_in_seconds=max_age)


def _set_session_cookie(response: Response, user: User, workspace: Workspace) -> int:
    settings = get_settings()
    max_age = settings.access_token_minutes * 60
    response.set_cookie(
        SESSION_COOKIE,
        create_access_token(user.id, user.role.value, user.token_version, workspace.value),
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api",
    )
    return max_age


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    """Sign out. A valid session is revoked server-side (every device of this user), so a
    copied token cannot be reused; the cookie is always cleared."""
    try:
        user = get_current_user(request, db)
    except HTTPException:
        user = None
    if user is not None:
        revoke_sessions(user)
        record_event(
            db,
            action="auth.logout",
            entity_type="user",
            entity_id=user.id,
            actor=user,
            summary=f"{user.username} signed out",
            request=request,
        )
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/api")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=SessionUserOut)
def me(
    user: User = Depends(get_current_user), workspace: Workspace = Depends(session_workspace)
) -> SessionUserOut:
    return _session_user(user, workspace)


@router.post("/change-password", response_model=SessionUserOut)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(session_workspace),
) -> SessionUserOut:
    """Change your own password. Other sessions are signed out; this one continues."""
    acct = throttle.account_key(user.username)
    if lock := throttle.check(db, [acct]):
        raise _locked(lock.retry_after_seconds)
    if not verify_password(body.current_password, user.password_hash):
        triggered = throttle.register_failure(db, acct, None)
        record_event(
            db,
            action="auth.password_change_failed",
            entity_type="user",
            entity_id=user.id,
            actor=user,
            summary="Password change refused: current password incorrect",
            request=request,
        )
        db.commit()
        if triggered:
            raise _locked(triggered.retry_after_seconds)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is incorrect.")
    if error := validate_password(body.new_password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error)
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose a password different from the current one.",
        )
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.must_change_password = False
    revoke_sessions(user)
    throttle.register_success(db, acct)
    record_event(
        db,
        action="auth.password_changed",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        summary=f"{user.username} changed their password",
        request=request,
    )
    db.commit()
    _set_session_cookie(response, user, workspace)  # keep this device signed in
    return _session_user(user, workspace)
