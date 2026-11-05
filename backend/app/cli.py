r"""Management commands.

    uv run python -m app.cli create-admin --username derrick \
        --email you@example.com --name "Your Name"
    uv run python -m app.cli load-sample
    uv run python -m app.cli clear-sample --yes

create-admin reads the password from LOGITRACK_ADMIN_PASSWORD or prompts for it.
"""

import argparse
import getpass
import os
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, or_, select

from .audit import record_event
from .db import SessionLocal
from .models import Role, User, UserStatus
from .sample_data import clear_sample_data, load_sample_data
from .security import MAX_PASSWORD_BYTES, hash_password


def validate_password(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
    if not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        return "Password must contain letters and numbers."
    if all(c.isalnum() for c in password):
        return "Password must contain at least one symbol."
    return None


def create_admin(args: argparse.Namespace) -> int:
    try:
        email = validate_email(args.email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        print(f"Invalid email: {exc}", file=sys.stderr)
        return 2
    password = os.environ.get("LOGITRACK_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    if error := validate_password(password):
        print(error, file=sys.stderr)
        return 2
    with SessionLocal() as db:
        exists = db.scalar(
            select(User).where(
                or_(
                    func.lower(User.username) == args.username.lower(),
                    func.lower(User.email) == email.lower(),
                )
            )
        )
        if exists:
            print("A user with that username or email already exists.", file=sys.stderr)
            return 1
        user = User(
            username=args.username,
            email=email,
            full_name=args.name,
            password_hash=hash_password(password),
            role=Role.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        db.flush()
        record_event(
            db,
            action="user.created",
            entity_type="user",
            entity_id=user.id,
            summary=f"Administrator {user.username} created via CLI",
        )
        db.commit()
        print(f"Created administrator '{user.username}' (id {user.id}).")
    return 0


def load_sample(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            counts = load_sample_data(db)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
    print(f"Sample data loaded (clearly flagged in the UI): {counts}")
    return 0


def clear_sample(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Pass --yes to confirm deleting the sample dataset.", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        try:
            clear_sample_data(db)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
    print("Sample data removed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="LogiTrack management")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Create an active administrator account")
    p.add_argument("--username", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=create_admin)

    sub.add_parser("load-sample", help="Load the labelled sample dataset").set_defaults(
        func=load_sample
    )

    p = sub.add_parser("clear-sample", help="Delete the sample dataset")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=clear_sample)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
