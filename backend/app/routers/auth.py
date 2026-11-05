from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import record_event
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User, UserStatus
from ..schemas import LoginRequest, LoginResponse, UserOut
from ..security import (
    SESSION_COOKIE,
    create_access_token,
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
    settings = get_settings()
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

    max_age = settings.access_token_minutes * 60
    response.set_cookie(
        SESSION_COOKIE,
        create_access_token(user.id, user.role.value),
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api",
    )
    return LoginResponse(user=UserOut.model_validate(user), expires_in_seconds=max_age)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/api")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
