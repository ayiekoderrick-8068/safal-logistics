"""User management (administrators only).

Uses the existing account model and session mechanism - no second auth system:
- New accounts and resets use a temporary password and must change it at next sign-in.
- Role changes, deactivation and password resets revoke the user's existing sessions.
- An administrator cannot demote or deactivate themselves, and the last active
  administrator can never be demoted or deactivated (no lock-out).
- Every change is audited; passwords are never logged or returned.
"""

from datetime import UTC, datetime
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..audit import record_event
from ..db import get_db
from ..deps import require_roles, revoke_sessions
from ..models import Role, User, UserStatus
from ..schemas import AdminUserOut, PasswordReset, UserCreate, UserUpdate
from ..security import hash_password, validate_password
from ..services import throttle

router = APIRouter(prefix="/api/users", tags=["users"])
Admin = Annotated[User, Depends(require_roles())]  # administrators only
DB = Annotated[Session, Depends(get_db)]


def _get(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _password_ok(password: str) -> None:
    if error := validate_password(password):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error)


def _active_admins(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(User.id)).where(
                User.role == Role.ADMIN, User.status == UserStatus.ACTIVE
            )
        )
        or 0
    )


@router.get("", response_model=list[AdminUserOut])
def list_users(
    db: DB,
    _: Admin,
    q: str | None = Query(None, max_length=80),
    role: Role | None = None,
    status_: UserStatus | None = Query(None, alias="status"),
) -> list[User]:
    query = select(User).order_by(User.full_name).limit(500)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(User.username.ilike(like), User.email.ilike(like), User.full_name.ilike(like))
        )
    if role:
        query = query.where(User.role == role)
    if status_:
        query = query.where(User.status == status_)
    return list(db.scalars(query))


@router.post("", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, db: DB, admin: Admin) -> User:
    try:
        email = validate_email(body.email, check_deliverability=False).normalized
    except EmailNotValidError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a valid email address."
        ) from None
    _password_ok(body.temporary_password)
    clash = db.scalar(
        select(User.id).where(
            or_(
                func.lower(User.username) == body.username,
                func.lower(User.email) == email.lower(),
            )
        )
    )
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username or email is already in use.")
    user = User(
        username=body.username,
        email=email,
        full_name=body.full_name,
        role=body.role,
        status=UserStatus.ACTIVE,
        password_hash=hash_password(body.temporary_password),
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    record_event(
        db,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        request=request,
        summary=f"User {user.username} created with role {user.role.value}",
        changes={"role": user.role.value},
    )
    db.commit()
    return user


@router.patch("/{user_id}", response_model=AdminUserOut)
def update_user(user_id: int, body: UserUpdate, request: Request, db: DB, admin: Admin) -> User:
    user = _get(db, user_id)
    fields = body.model_fields_set
    changes: dict[str, object] = {}
    new_role = body.role if "role" in fields and body.role is not None else user.role
    new_status = UserStatus(body.status) if "status" in fields and body.status else user.status

    if user.id == admin.id and (new_role != Role.ADMIN or new_status != UserStatus.ACTIVE):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You cannot remove your own administrator access. Ask another administrator.",
        )
    losing_admin = (
        user.role == Role.ADMIN
        and user.status == UserStatus.ACTIVE
        and (new_role != Role.ADMIN or new_status != UserStatus.ACTIVE)
    )
    if losing_admin and _active_admins(db) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "LogiTrack needs at least one active administrator."
        )

    if "full_name" in fields and body.full_name and body.full_name != user.full_name:
        changes["full_name"] = body.full_name
        user.full_name = " ".join(body.full_name.split())
    if new_role != user.role:
        changes["role"] = {"from": user.role.value, "to": new_role.value}
        user.role = new_role
    if new_status != user.status:
        changes["status"] = {"from": user.status.value, "to": new_status.value}
        user.status = new_status
    if "role" in changes or "status" in changes:
        revoke_sessions(user)  # access changes take effect immediately
    if changes:
        record_event(
            db,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            actor=admin,
            request=request,
            summary=f"User {user.username} updated",
            changes=changes,
        )
        db.commit()
    return user


@router.post("/{user_id}/reset-password", response_model=AdminUserOut)
def reset_password(
    user_id: int, body: PasswordReset, request: Request, db: DB, admin: Admin
) -> User:
    user = _get(db, user_id)
    _password_ok(body.temporary_password)
    user.password_hash = hash_password(body.temporary_password)
    user.password_changed_at = datetime.now(UTC)
    user.must_change_password = True
    revoke_sessions(user)
    record_event(
        db,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        request=request,
        summary=f"Temporary password issued for {user.username}",
    )
    db.commit()
    for typed in {user.username, user.email}:  # clear any sign-in lockout for this account
        throttle.unlock(db, identifier=typed)
    return user
