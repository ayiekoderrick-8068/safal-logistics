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

router = APIRouter(prefix="/api/auth", tags=["auth"])

_INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> LoginResponse:
    settings = get_settings()
    identifier = body.username.strip().lower()
    user = db.scalar(
        select(User).where(
            or_(func.lower(User.username) == identifier, func.lower(User.email) == identifier)
        )
    )

    if user is None:
        verify_against_dummy(body.password)
        record_event(
            db,
            action="auth.login_failed",
            entity_type="user",
            summary="Failed login for unknown user",
            request=request,
        )
        db.commit()
        raise _INVALID

    if not verify_password(body.password, user.password_hash):
        record_event(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            summary=f"Failed login for {user.username}",
            request=request,
        )
        db.commit()
        raise _INVALID

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is not active")

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
