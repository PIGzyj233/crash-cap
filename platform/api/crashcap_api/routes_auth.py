"""Local account lifecycle and upload-only credential management."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import (
    COOKIE,
    check_origin,
    csrf_token,
    digest,
    new_session,
    normalize_username,
    password_hash,
    revoke_all,
    throttle,
    user_view,
    verify_password,
)
from .errors import ApiError
from .identity import current_principal
from .ids import new_id
from .models import AccessToken, AuthSession, User
from .routes import SessionDep, SettingsDep
from .services.common import operation_log

router = APIRouter(prefix="/api/v3", tags=["identity"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Credentials(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class Registration(Credentials):
    display_name: str = Field(min_length=1, max_length=128)


class PasswordChange(Strict):
    current_password: SecretStr = Field(max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class ProfilePatch(Strict):
    display_name: str = Field(min_length=1, max_length=128)


class TokenInput(Strict):
    name: str = Field(min_length=1, max_length=128)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class UserPatch(Strict):
    enabled: bool | None = None
    role: Literal["member", "admin"] | None = None


class UserView(Strict):
    id: str
    username: str
    display_name: str
    kind: str
    role: str
    enabled: bool
    must_change_password: bool


class IdentityView(Strict):
    user: UserView
    csrf_token: str


class TokenView(Strict):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    name: str
    scope: str
    issued_by_user_id: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class IssuedToken(TokenView):
    token: str


class TemporaryPassword(Strict):
    temporary_password: str


def human(session: SessionDep) -> User:
    principal = current_principal.get()
    row = account(session, principal.user_id)
    credential = session.get(AuthSession, principal.credential_id)
    if not row.enabled or credential is None or credential.revoked_at is not None:
        raise ApiError("UNAUTHENTICATED", "Session revoked", status_code=401)
    if row is None or row.kind != "human":
        raise ApiError("FORBIDDEN", "A human account is required", status_code=403)
    return row


def admin() -> None:
    if current_principal.get().role != "admin":
        raise ApiError("FORBIDDEN", "Administrator access required", status_code=403)


def account(session: SessionDep, user_id: str) -> User:
    # Login, reset, password changes and token issuance share this user-row lock.
    # Revocation must run after an earlier login commits its newly created session.
    row = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if row is None:
        raise ApiError("NOT_FOUND", "User not found", status_code=404)
    return row


def audit(
    session: SessionDep, action: str, uid: str, request: Request, *, token_id: str | None = None
) -> None:
    entry = operation_log(
        session,
        action=action,
        target_type="access_token" if token_id else "user",
        target_id=token_id or uid,
        workspace_id=None,
        request=request,
        details={"user_id": uid} if token_id else None,
    )
    if action in {"account.register", "account.login"}:
        row = account(session, uid)
        entry.actor_user_id, entry.actor, entry.actor_name = row.id, row.username, row.display_name
        entry.auth_method = "password"


def public_attempt(
    request: Request, session: SessionDep, settings: SettingsDep, username: str
) -> None:
    check_origin(request, settings)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise ApiError("VALIDATION", "JSON required", status_code=415)
    ip = request.client.host if request.client else "unknown"
    throttle(session, "ip:" + digest(ip), settings.auth_rate_limit)
    throttle(session, "name:" + digest(username.strip().lower()), settings.auth_rate_limit)


@router.post("/auth/register", response_model=UserView, status_code=201)
def register(
    body: Registration, request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, object]:
    public_attempt(request, session, settings, body.username)
    name = normalize_username(body.username)
    display = body.display_name.strip()
    if not display:
        raise ApiError("VALIDATION", "Display name is required", status_code=422)
    row = User(
        id=new_id("usr"),
        username=name,
        display_name=display,
        password_hash=password_hash(body.password.get_secret_value()),
        kind="human",
        role="member",
        enabled=True,
    )
    session.add(row)
    try:
        session.flush()
        audit(session, "account.register", row.id, request)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("USERNAME_TAKEN", "Username is unavailable", status_code=409) from exc
    return user_view(row)


@router.post("/auth/login", response_model=IdentityView)
def login(
    body: Credentials,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, object]:
    public_attempt(request, session, settings, body.username)
    row = session.scalar(
        select(User).where(User.username == body.username.strip().lower()).with_for_update()
    )
    valid = verify_password(row.password_hash if row else None, body.password.get_secret_value())
    if not valid or row is None or not row.enabled or row.kind != "human":
        audit(session, "account.login_failed", "usr_system", request)
        session.commit()
        raise ApiError("INVALID_CREDENTIALS", "Invalid username or password", status_code=401)
    old = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == digest(request.cookies.get(COOKIE, "")))
    )
    if old:
        old.revoked_at = datetime.now(UTC)
    # A temporary password may establish only one restricted session.
    if row.must_change_password:
        revoke_all(session, row.id)
        row.password_hash = password_hash(secrets.token_urlsafe(32))
    raw, csrf = new_session(session, row, settings)
    audit(session, "account.login", row.id, request)
    session.commit()
    response.set_cookie(COOKIE, raw, httponly=True, samesite="lax", secure=False, path="/api")
    return {"user": user_view(row), "csrf_token": csrf}


@router.get("/auth/me", response_model=IdentityView)
def me(request: Request, session: SessionDep) -> dict[str, object]:
    return {
        "user": user_view(human(session)),
        "csrf_token": csrf_token(request.cookies.get(COOKIE, "")),
    }


@router.patch("/auth/me", response_model=UserView)
def profile(body: ProfilePatch, request: Request, session: SessionDep) -> dict[str, object]:
    row = human(session)
    if not body.display_name.strip():
        raise ApiError("VALIDATION", "Display name is required", status_code=422)
    row.display_name = body.display_name.strip()
    audit(session, "account.profile", row.id, request)
    session.commit()
    return user_view(row)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, session: SessionDep) -> None:
    row = session.get(AuthSession, current_principal.get().credential_id)
    if row:
        row.revoked_at = datetime.now(UTC)
    session.commit()
    response.delete_cookie(COOKIE, path="/api")


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordChange, request: Request, response: Response, session: SessionDep
) -> None:
    row = human(session)
    if not row.must_change_password and not verify_password(
        row.password_hash, body.current_password.get_secret_value()
    ):
        raise ApiError("INVALID_CREDENTIALS", "Current password is incorrect", status_code=403)
    row.password_hash = password_hash(body.new_password.get_secret_value())
    row.must_change_password = False
    revoke_all(session, row.id)
    audit(session, "account.password_changed", row.id, request)
    session.commit()
    response.delete_cookie(COOKIE, path="/api")


@router.get("/users", response_model=list[UserView])
def users(
    session: SessionDep, q: str = "", limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, object]]:
    return [
        user_view(row)
        for row in session.scalars(
            select(User)
            .where(
                User.display_name.contains(q, autoescape=True)
                | User.username.contains(q.lower(), autoescape=True)
            )
            .order_by(User.username)
            .limit(limit)
        )
    ]


@router.get("/admin/users", response_model=list[UserView])
def admin_users(
    session: SessionDep, q: str = "", limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, object]]:
    admin()
    return users(session, q, limit)


@router.patch("/admin/users/{user_id}", response_model=UserView)
def edit_user(
    user_id: str, body: UserPatch, request: Request, session: SessionDep
) -> dict[str, object]:
    admin()
    # Serialize admin changes so concurrent requests cannot remove the last admin.
    admins = list(
        session.scalars(
            select(User)
            .where(User.role == "admin", User.enabled.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
    )
    row = account(session, user_id)
    if row.kind in {"system", "legacy"} or body.role == "admin" and row.kind != "human":
        raise ApiError("FORBIDDEN", "Reserved account", status_code=403)
    if (
        row.role == "admin"
        and row.enabled
        and len(admins) == 1
        and (body.enabled is False or body.role == "member")
    ):
        raise ApiError("CONFLICT", "Cannot remove the last enabled administrator", status_code=409)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.role is not None:
        row.role = body.role
    revoke_all(session, row.id)
    audit(session, "account.admin_update", row.id, request)
    session.commit()
    return user_view(row)


@router.post("/admin/users/{user_id}:reset-password", response_model=TemporaryPassword)
def reset_password(user_id: str, request: Request, session: SessionDep) -> dict[str, str]:
    admin()
    row = account(session, user_id)
    if row.kind != "human":
        raise ApiError("FORBIDDEN", "Only human accounts have passwords", status_code=403)
    temporary = secrets.token_urlsafe(20)
    row.password_hash, row.must_change_password = password_hash(temporary), True
    revoke_all(session, row.id)
    audit(session, "account.password_reset", row.id, request)
    session.commit()
    return {"temporary_password": temporary}


def token_target(session: SessionDep, user_id: str | None) -> User:
    if user_id is None:
        return human(session)
    admin()
    row = account(session, user_id)
    if row.kind != "service":
        raise ApiError("FORBIDDEN", "Expected a service account", status_code=403)
    return row


@router.get("/me/tokens", response_model=list[TokenView])
@router.get("/admin/service-users/{user_id}/tokens", response_model=list[TokenView])
def list_tokens(session: SessionDep, user_id: str | None = None) -> list[AccessToken]:
    row = token_target(session, user_id)
    return list(
        session.scalars(
            select(AccessToken)
            .where(AccessToken.user_id == row.id)
            .order_by(AccessToken.created_at.desc())
        )
    )


@router.post("/me/tokens", response_model=IssuedToken, status_code=201)
@router.post("/admin/service-users/{user_id}/tokens", response_model=IssuedToken, status_code=201)
def issue_token(
    body: TokenInput, request: Request, session: SessionDep, user_id: str | None = None
) -> dict[str, object]:
    row = token_target(session, user_id)
    if not row.enabled or not body.name.strip():
        raise ApiError("VALIDATION", "Enabled account and token name required", status_code=422)
    raw = "ccp_" + secrets.token_urlsafe(32)
    token = AccessToken(
        id=new_id("tok"),
        user_id=row.id,
        name=body.name.strip(),
        token_hash=digest(raw),
        issued_by_user_id=current_principal.get().user_id,
        scope="upload",
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days),
    )
    session.add(token)
    audit(session, "token.issue", row.id, request, token_id=token.id)
    session.commit()
    return {**TokenView.model_validate(token).model_dump(), "token": raw}


@router.post("/me/tokens/{token_id}:revoke", status_code=204)
@router.post("/admin/service-users/{user_id}/tokens/{token_id}:revoke", status_code=204)
def revoke_token(
    token_id: str, request: Request, session: SessionDep, user_id: str | None = None
) -> None:
    row = token_target(session, user_id)
    token = session.get(AccessToken, token_id)
    if token is None or token.user_id != row.id:
        raise ApiError("NOT_FOUND", "Token not found", status_code=404)
    token.revoked_at = datetime.now(UTC)
    audit(session, "token.revoke", row.id, request, token_id=token.id)
    session.commit()
