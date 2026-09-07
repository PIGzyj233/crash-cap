"""Credential verification, revocation and shared throttling behind one identity interface."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .identity import Principal
from .ids import new_id
from .models import AccessToken, AuthRateLimit, AuthSession, User

COOKIE = "crashcap_session"
PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
BUILTINS = (
    ("usr_ci", "ci-bot", "CI", "service", True),
    ("usr_system", "system", "后台系统", "system", False),
    ("usr_legacy", "legacy-unknown", "历史未知用户", "legacy", False),
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def seed_users(session: Session) -> None:
    for uid, name, display, kind, enabled in BUILTINS:
        if session.get(User, uid) is None:
            session.add(
                User(
                    id=uid,
                    username=name,
                    display_name=display,
                    kind=kind,
                    enabled=enabled,
                    role="member",
                )
            )
    session.commit()


def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ApiError("VALIDATION", "Password must contain 12–128 characters", status_code=422)
    return PASSWORDS.hash(password)


def verify_password(value: str | None, password: str) -> bool:
    try:
        return PASSWORDS.verify(value or DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False


def normalize_username(value: str) -> str:
    name = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", name):
        raise ApiError(
            "VALIDATION",
            "Username must be 3–64 ASCII letters, digits, dots, underscores or hyphens",
            status_code=422,
        )
    return name


def user_view(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "kind": user.kind,
        "role": user.role,
        "enabled": user.enabled,
        "must_change_password": user.must_change_password,
    }


def revoke_all(session: Session, user_id: str) -> None:
    for model in (AuthSession, AccessToken):
        session.execute(
            update(model)
            .where(model.user_id == user_id, model.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )


def check_origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.auth_origin:
        raise ApiError("CSRF_REJECTED", "A same-origin request is required", status_code=403)


def throttle(session: Session, key: str, limit: int) -> None:
    window = int(time.time()) // 300
    insert = (
        sqlite_insert
        if session.bind is not None and session.bind.dialect.name == "sqlite"
        else pg_insert
    )
    statement = insert(AuthRateLimit).values(key=key, window=window, count=0)
    session.execute(statement.on_conflict_do_nothing(index_elements=["key"]))
    row = session.scalar(select(AuthRateLimit).where(AuthRateLimit.key == key).with_for_update())
    assert row is not None
    if row.window != window:
        row.window, row.count = window, 0
    row.count += 1
    blocked = row.count > limit
    session.commit()
    if blocked:
        raise ApiError("RATE_LIMITED", "Too many attempts; retry in five minutes", status_code=429)


def csrf_token(raw: str) -> str:
    return digest("csrf:" + raw)


def new_session(session: Session, user: User, settings: Settings) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    csrf = csrf_token(raw)
    now = datetime.now(UTC)
    session.add(
        AuthSession(
            id=new_id("ses"),
            user_id=user.id,
            token_hash=digest(raw),
            csrf_hash=digest(csrf),
            expires_at=now + timedelta(seconds=settings.session_max_seconds),
            created_at=now,
            last_used_at=now,
        )
    )
    return raw, csrf


def token_allowed(method: str, path: str) -> bool:
    if method == "GET":
        return bool(re.fullmatch(r"/api/v3/(workspaces(?:/[^/]+)?|uploads(?:/[^/:]+)?)", path))
    return method == "POST" and bool(
        re.fullmatch(r"/api/v3/(uploads:init|uploads/[^/:]+:complete)", path)
    )


def authenticate(
    request: Request, session: Session, settings: Settings, *, touch: bool = True
) -> Principal:
    now = datetime.now(UTC)
    credential: AccessToken | AuthSession | None = None
    header = request.headers.get("authorization")
    method = "session"
    if header is not None:
        method = "token"
        if header.startswith("Bearer ") and len(header) < 1024:
            credential = session.scalar(
                select(AccessToken).where(AccessToken.token_hash == digest(header[7:]))
            )
    else:
        raw = request.cookies.get(COOKIE, "")
        if raw and len(raw) < 1024:
            credential = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == digest(raw))
            )
    if credential is None or credential.revoked_at is not None or utc(credential.expires_at) <= now:
        raise ApiError(
            "UNAUTHENTICATED", "Please sign in or supply a valid platform token", status_code=401
        )
    if (
        isinstance(credential, AuthSession)
        and utc(credential.last_used_at) + timedelta(seconds=settings.session_idle_seconds) <= now
    ):
        raise ApiError("UNAUTHENTICATED", "Session expired", status_code=401)
    user = session.get(User, credential.user_id)
    if user is None or not user.enabled:
        raise ApiError("UNAUTHENTICATED", "Account unavailable", status_code=401)
    path = request.url.path.rstrip("/")
    if isinstance(credential, AccessToken):
        if (
            credential.scope != "upload"
            or user.must_change_password
            or not token_allowed(request.method, path)
        ):
            raise ApiError("FORBIDDEN", "Token does not permit this operation", status_code=403)
    elif request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request, settings)
        if not secrets.compare_digest(
            digest(request.headers.get("x-csrf-token", "")), credential.csrf_hash
        ):
            raise ApiError("CSRF_REJECTED", "Invalid CSRF token", status_code=403)
    if user.must_change_password and (request.method, path) not in {
        ("GET", "/api/v3/auth/me"),
        ("POST", "/api/v3/auth/password"),
        ("POST", "/api/v3/auth/logout"),
    }:
        raise ApiError(
            "PASSWORD_CHANGE_REQUIRED", "Change your temporary password first", status_code=403
        )
    if touch:
        credential.last_used_at = now
        session.commit()
    return Principal(
        user.id,
        user.username,
        user.display_name,
        user.kind,
        user.role,
        method,
        credential.id,
        user.must_change_password,
    )
