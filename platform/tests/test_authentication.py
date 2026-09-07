"""Exercise the real authentication interface, including HTTP-only deployment behavior."""

from datetime import UTC, datetime, timedelta

import pytest
from crashcap_api.app import create_app
from crashcap_api.auth import COOKIE, digest
from crashcap_api.config import Settings
from crashcap_api.models import AccessToken, AuthSession, OperationLog, Upload, User
from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "a locally unique password"


@pytest.fixture
def auth_app(tmp_path):
    return create_app(Settings.for_test(tmp_path))


def client_for(app, username="alice", *, admin=False):
    client = TestClient(app, headers={"Origin": "http://testserver"})
    response = client.post(
        "/api/v3/auth/register",
        json={"username": username, "display_name": username.title(), "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    uid = response.json()["id"]
    if admin:
        with app.state.database.sessions.begin() as session:
            session.get(User, uid).role = "admin"
    response = client.post("/api/v3/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client, uid


def init_upload(client):
    result = client.post(
        "/api/v3/uploads:init",
        json={
            "workspace_id": None,
            "file_kind": "pe",
            "filename": "endpoint.exe",
            "size": 12,
            "source": "cli",
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_all_business_routes_require_authentication(auth_app):
    with TestClient(auth_app) as client:
        for path, operations in auth_app.openapi()["paths"].items():
            if path in {"/api/v3/auth/register", "/api/v3/auth/login"}:
                continue
            for method in operations:
                if method not in {"get", "post", "patch", "put", "delete"}:
                    continue
                result = client.request(method.upper(), path)
                assert result.status_code == 401, (method, path, result.text)
        assert client.get("/healthz").status_code == 200


def test_registration_cookie_csrf_and_bearer_precedence(auth_app):
    client, uid = client_for(auth_app)
    assert client.get("/api/v3/auth/me").json()["user"]["id"] == uid
    duplicate = client.post(
        "/api/v3/auth/register",
        json={"username": "ALICE", "display_name": "Duplicate", "password": PASSWORD},
    )
    assert duplicate.status_code == 409
    assert (
        client.post(
            "/api/v3/workspaces", json={"name": "test"}, headers={"Origin": "http://evil.test"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v3/workspaces", json={"name": "test"}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v3/workspaces", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert client.get("/api/v3/admin/users").status_code == 403
    login = client.post("/api/v3/auth/login", json={"username": "alice", "password": PASSWORD})
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api" in cookie
    assert "Secure" not in cookie and "Domain" not in cookie
    assert (
        client.post(
            "/api/v3/auth/login", json={"username": "missing", "password": PASSWORD}
        ).status_code
        == 401
    )
    with auth_app.state.database.sessions() as session:
        user = session.get(User, uid)
        assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash
        assert all(
            PASSWORD not in str(log.details) for log in session.scalars(select(OperationLog))
        )


def test_ci_tokens_are_scoped_revocable_and_not_anonymous(auth_app):
    admin, _ = client_for(auth_app, admin=True)
    issued = admin.post("/api/v3/admin/service-users/usr_ci/tokens", json={"name": "nightly"})
    assert issued.status_code == 201, issued.text
    token = issued.json()
    ci = TestClient(auth_app, headers={"Authorization": f"Bearer {token['token']}"})
    upload = init_upload(ci)
    assert upload["uploaded_by"]["id"] == "usr_ci"
    assert ci.get("/api/v3/workspaces").status_code == 200
    for method, path in [
        ("GET", "/api/v3/artifacts"),
        ("GET", "/api/v3/admin/users"),
        ("POST", "/api/v3/me/tokens"),
        ("PATCH", "/api/v3/groups/any"),
        ("POST", "/api/v3/workspaces"),
    ]:
        assert ci.request(method, path, json={}).status_code == 403
    assert "token" not in admin.get("/api/v3/admin/service-users/usr_ci/tokens").json()[0]
    assert (
        admin.post(f"/api/v3/admin/service-users/usr_ci/tokens/{token['id']}:revoke").status_code
        == 204
    )
    assert ci.get("/api/v3/workspaces").status_code == 401
    with auth_app.state.database.sessions() as session:
        row = session.get(Upload, upload["upload_id"])
        assert row.access_token_id == token["id"] and row.uploaded_by_user_id == "usr_ci"
        assert session.get(AccessToken, token["id"]).token_hash == digest(token["token"])
    anonymous = TestClient(auth_app)
    assert anonymous.post("/api/v3/uploads:init", json={}).status_code == 401


def test_attribution_snapshots_and_completion_ownership(auth_app):
    alice, aid = client_for(auth_app)
    bob, bid = client_for(auth_app, "bob")
    upload = init_upload(alice)
    second = init_upload(bob)
    assert upload["uploaded_by"]["id"] == aid and second["uploaded_by"]["id"] == bid
    assert bob.post(f"/api/v3/uploads/{upload['upload_id']}:complete", json={}).status_code == 403
    assert alice.patch("/api/v3/auth/me", json={"display_name": "Renamed"}).status_code == 200
    assert (
        alice.get(f"/api/v3/uploads/{upload['upload_id']}").json()["uploaded_by"]["display_name"]
        == "Alice"
    )
    listed = alice.get("/api/v3/uploads", params={"uploaded_by_user_id": aid}).json()["items"]
    assert [row["upload_id"] for row in listed] == [upload["upload_id"]]
    forged = {
        "workspace_id": None,
        "file_kind": "pe",
        "filename": "bad.exe",
        "size": 12,
        "uploaded_by_user_id": bid,
    }
    assert alice.post("/api/v3/uploads:init", json=forged).status_code == 422
    token = alice.post("/api/v3/me/tokens", json={"name": "my cli"}).json()["token"]
    cli = TestClient(auth_app, headers={"Authorization": f"Bearer {token}"})
    assert cli.get(f"/api/v3/uploads/{second['upload_id']}").status_code == 403
    assert cli.get(f"/api/v3/uploads/{upload['upload_id']}").status_code == 200


def test_password_change_revokes_sessions_and_tokens(auth_app):
    client, uid = client_for(auth_app)
    issued = client.post("/api/v3/me/tokens", json={"name": "personal"}).json()["token"]
    old_cookie = client.cookies.get(COOKIE)
    result = client.post(
        "/api/v3/auth/password",
        json={"current_password": PASSWORD, "new_password": "another long password"},
    )
    assert result.status_code == 204, result.text
    assert client.get("/api/v3/auth/me").status_code == 401
    client.cookies.set(COOKIE, old_cookie)
    assert client.get("/api/v3/auth/me").status_code == 401
    assert (
        client.get("/api/v3/workspaces", headers={"Authorization": f"Bearer {issued}"}).status_code
        == 401
    )
    with auth_app.state.database.sessions() as session:
        assert all(
            row.revoked_at
            for row in session.scalars(select(AuthSession).where(AuthSession.user_id == uid))
        )


def test_temporary_password_is_single_use_and_forces_change(auth_app):
    admin, _ = client_for(auth_app, "admin", admin=True)
    alice, uid = client_for(auth_app)
    temporary = admin.post(f"/api/v3/admin/users/{uid}:reset-password").json()["temporary_password"]
    assert alice.get("/api/v3/auth/me").status_code == 401
    login = alice.post("/api/v3/auth/login", json={"username": "alice", "password": temporary})
    assert login.status_code == 200
    alice.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert alice.get("/api/v3/workspaces").json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    other = TestClient(auth_app, headers={"Origin": "http://testserver"})
    assert (
        other.post(
            "/api/v3/auth/login", json={"username": "alice", "password": temporary}
        ).status_code
        == 401
    )
    changed = alice.post(
        "/api/v3/auth/password",
        json={"current_password": "", "new_password": "a fresh unique password"},
    )
    assert changed.status_code == 204, changed.text


def test_disable_and_last_admin_protection(auth_app):
    admin, uid = client_for(auth_app, "admin", admin=True)
    alice, aid = client_for(auth_app)
    assert admin.patch(f"/api/v3/admin/users/{uid}", json={"enabled": False}).status_code == 409
    assert admin.patch("/api/v3/admin/users/usr_ci", json={"role": "admin"}).status_code == 403
    assert admin.patch(f"/api/v3/admin/users/{aid}", json={"enabled": False}).status_code == 200
    assert alice.get("/api/v3/auth/me").status_code == 401
    with auth_app.state.database.sessions() as session:
        assert session.get(User, aid) is not None


def test_shared_throttling_and_expiry(auth_app):
    client, _ = client_for(auth_app)
    with auth_app.state.database.sessions.begin() as session:
        row = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == digest(client.cookies.get(COOKIE)))
        )
        row.last_used_at = datetime.now(UTC) - timedelta(hours=3)
    assert client.get("/api/v3/auth/me").status_code == 401
    auth_app.state.settings.auth_rate_limit = 2
    first = TestClient(auth_app, headers={"Origin": "http://testserver"})
    assert (
        first.post(
            "/api/v3/auth/login", json={"username": "alice", "password": "incorrect"}
        ).status_code
        == 429
    )


def test_client_cannot_supply_review_identity(auth_app):
    client, _ = client_for(auth_app)
    result = client.post(
        "/api/v3/symbol-catalog/pairs/any/reviews",
        json={
            "expected_version": 1,
            "state": "active",
            "reason": "reason",
            "reviewer": "someone else",
            "evidence": "evidence",
            "idempotency_key": "id",
        },
    )
    assert result.status_code == 422


@pytest.mark.parametrize(
    "extension,kind", [("exe", "pe"), ("dll", "pe"), ("pdb", "pdb"), ("dmp", "dmp")]
)
def test_verified_duplicate_uploads_keep_each_submitter(auth_app, extension, kind):
    from crashcap_api.models import ArtifactEntry, CatalogFile, OccurrenceSubmission
    from sqlalchemy import func

    from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes

    alice, aid = client_for(auth_app)
    bob, bid = client_for(auth_app, "bob")
    workspace = alice.post("/api/v3/workspaces", json={"name": "duplicate-test"}).json()["id"]
    payload = (
        dump_bytes(111)
        if kind == "dmp"
        else pdb_bytes("a" * 33)
        if kind == "pdb"
        else pe_bytes("a" * 33)
    )
    results = []
    for client, uid in [(alice, aid), (bob, bid)]:
        harness = Phase1Harness(client, auth_app, auth_app.state.settings)
        initialized = client.post(
            "/api/v3/uploads:init",
            json={
                "workspace_id": workspace,
                "file_kind": kind,
                "filename": f"test.{extension}",
                "size": len(payload),
            },
        ).json()
        harness._seed_upload(initialized["upload_id"], payload)
        completed = client.post(f"/api/v3/uploads/{initialized['upload_id']}:complete", json={})
        assert completed.status_code == 200, completed.text
        harness.drain()
        final = client.get(f"/api/v3/uploads/{initialized['upload_id']}").json()
        assert final["status"] == "ACCEPTED", final
        assert final["uploaded_by"]["id"] == uid
        results.append(final)
    with auth_app.state.database.sessions() as session:
        if kind == "dmp":
            assert results[0]["occurrence_id"] == results[1]["occurrence_id"]
            rows = list(session.scalars(select(OccurrenceSubmission)))
            assert {row.uploaded_by["id"] for row in rows} == {aid, bid}
        else:
            assert session.scalar(select(func.count()).select_from(CatalogFile)) == 1
            rows = list(session.scalars(select(ArtifactEntry)))
            assert {row.uploaded_by["id"] for row in rows} == {aid, bid}
    page = alice.get(
        f"/api/v3/workspaces/{workspace}/artifacts", params={"uploaded_by_user_id": aid}
    ).json()
    assert all(row["uploaded_by"]["id"] == aid for row in page["items"])
