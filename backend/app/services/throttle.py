"""Sign-in throttling (brute force and credential stuffing).

Two independent counters, stored in PostgreSQL so they hold across server processes:
  * account  - failures for one identifier (username/email, hashed), whether or not the
               account exists, so responses never reveal which usernames are real;
  * ip       - failures from one client address across all identifiers.

When either counter reaches its limit inside the window, sign-in from that key is refused
for the lockout period - *even with the correct password* - and the client receives HTTP 429
with a generic message and a Retry-After header. Locks expire automatically; an administrator
can clear one early with ``python -m app.cli unlock-login``. A successful sign-in clears the
account counter.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AuthThrottle


def account_key(identifier: str) -> str:
    norm = identifier.strip().lower().encode()
    return "acct:" + hashlib.sha256(norm).hexdigest()


def ip_key(ip: str | None) -> str | None:
    return f"ip:{ip}" if ip else None


@dataclass(frozen=True)
class Lock:
    retry_after_seconds: int


def _lock_row(db: Session, key: str, now: datetime) -> AuthThrottle:
    # Upsert then lock the row so concurrent attempts are counted exactly.
    db.execute(
        insert(AuthThrottle)
        .values(key=key, failures=0, window_started_at=now)
        .on_conflict_do_nothing(index_elements=[AuthThrottle.key])
    )
    return db.scalars(select(AuthThrottle).where(AuthThrottle.key == key).with_for_update()).one()


def check(db: Session, keys: list[str], now: datetime | None = None) -> Lock | None:
    """Return the longest active lock among the keys, if any."""
    now = now or datetime.now(UTC)
    rows = db.scalars(
        select(AuthThrottle).where(AuthThrottle.key.in_(keys), AuthThrottle.locked_until > now)
    ).all()
    if not rows:
        return None
    until = max(r.locked_until for r in rows if r.locked_until)
    return Lock(retry_after_seconds=max(1, math.ceil((until - now).total_seconds())))


def register_failure(
    db: Session, acct: str, ip: str | None, now: datetime | None = None
) -> Lock | None:
    """Count a failed attempt; returns the lock if this attempt triggered one."""
    s = get_settings()
    now = now or datetime.now(UTC)
    window = timedelta(minutes=s.login_window_minutes)
    lockout = timedelta(minutes=s.login_lockout_minutes)
    triggered: Lock | None = None
    for key, limit in ((acct, s.login_max_failures), (ip, s.login_ip_max_failures)):
        if key is None:
            continue
        row = _lock_row(db, key, now)
        if now - row.window_started_at > window:
            row.failures, row.window_started_at = 0, now
        row.failures += 1
        if row.failures >= limit:
            row.locked_until = now + lockout
            row.failures, row.window_started_at = 0, now  # fresh window after the lock
            triggered = Lock(retry_after_seconds=int(lockout.total_seconds()))
    return triggered


def register_success(db: Session, acct: str) -> None:
    db.execute(delete(AuthThrottle).where(AuthThrottle.key == acct))


def unlock(db: Session, identifier: str | None = None, ip: str | None = None) -> int:
    keys = [k for k in (account_key(identifier) if identifier else None, ip_key(ip)) if k]
    result = db.execute(delete(AuthThrottle).where(AuthThrottle.key.in_(keys)))
    db.commit()
    return result.rowcount or 0


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """Housekeeping: drop counters that are neither locked nor inside an active window."""
    now = now or datetime.now(UTC)
    window = timedelta(minutes=get_settings().login_window_minutes)
    result = db.execute(
        delete(AuthThrottle).where(
            (AuthThrottle.locked_until.is_(None)) | (AuthThrottle.locked_until < now),
            AuthThrottle.window_started_at < now - window,
        )
    )
    return result.rowcount or 0
