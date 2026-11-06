from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, revoke_sessions
from ..models import User, UserStatus
from ..schemas import ChangePasswordRequest, LoginRequest, LoginResponse, UserOut
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
    user.last_login_at = datetime.now(UTC)
    record_event(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        summary=f"{user.username} signed in",
        request=request,
    )
    db.commit()
    max_age = _set_session_cookie(response, user)
    return LoginResponse(user=UserOut.model_validate(user), expires_in_seconds=max_age)


def _set_session_cookie(response: Response, user: User) -> int:
    settings = get_settings()
    max_age = settings.access_token_minutes * 60
    response.set_cookie(
        SESSION_COOKIE,
        create_access_token(user.id, user.role.value, user.token_version),
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


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/change-password", response_model=UserOut)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
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
    _set_session_cookie(response, user)  # keep this device signed in with the new version
    return user
