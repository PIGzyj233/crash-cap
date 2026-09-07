"""Authentication races across independent app instances on an owned PostgreSQL schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from crashcap_api.app import create_app
from crashcap_api.auth import digest
from crashcap_api.config import Settings
from crashcap_api.models import AuthRateLimit, User
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from . import test_symbol_catalog_postgres as catalog_tests
from .test_authentication import PASSWORD, client_for

pg = catalog_tests.pg

pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
)


@pytest.fixture
def apps(pg, tmp_path):
    engine, _, _ = pg
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "database_url": engine.url.render_as_string(hide_password=False),
            "create_schema": False,
            "auth_rate_limit": 100,
        }
    )
    instances = [create_app(settings), create_app(settings)]
    yield instances
    for app in instances:
        app.state.database.dispose()


def concurrently(actions):
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def test_concurrent_registration_has_one_canonical_username(apps):
    clients = [TestClient(apps[i % 2], headers={"Origin": "http://testserver"}) for i in range(8)]
    names = ["Alice", "alice", "ALICE", " alice "] * 2
    responses = concurrently(
        [
            lambda client=client, name=name: client.post(
                "/api/v3/auth/register",
                json={"username": name, "display_name": "Alice", "password": PASSWORD},
            )
            for client, name in zip(clients, names, strict=True)
        ]
    )
    assert sorted(response.status_code for response in responses) == [201] + [409] * 7
    with apps[0].state.database.sessions() as session:
        assert (
            session.scalar(select(func.count()).select_from(User).where(User.username == "alice"))
            == 1
        )


def test_username_throttle_is_shared_and_normalized_across_workers_and_ips(apps):
    for app in apps:
        app.state.settings.auth_rate_limit = 3
    clients = [
        TestClient(
            apps[i % 2], headers={"Origin": "http://testserver"}, client=(f"192.0.2.{i + 1}", 50000)
        )
        for i in range(8)
    ]
    responses = concurrently(
        [
            lambda client=client, i=i: client.post(
                "/api/v3/auth/login",
                json={"username": " absent " if i % 2 else "ABSENT", "password": PASSWORD},
            )
            for i, client in enumerate(clients)
        ]
    )
    assert sorted(r.status_code for r in responses) == [401] * 3 + [429] * 5
    with apps[0].state.database.sessions() as session:
        row = session.get(AuthRateLimit, "name:" + digest("absent"))
        assert row.count == 8


def test_ip_throttle_is_shared_between_register_and_login(apps):
    for app in apps:
        app.state.settings.auth_rate_limit = 3
    clients = [TestClient(apps[i % 2], headers={"Origin": "http://testserver"}) for i in range(8)]
    responses = concurrently(
        [
            lambda client=client, i=i: client.post(
                "/api/v3/auth/register" if i % 2 else "/api/v3/auth/login",
                json={
                    "username": f"person-{i}",
                    "password": PASSWORD,
                    **({"display_name": f"Person {i}"} if i % 2 else {}),
                },
            )
            for i, client in enumerate(clients)
        ]
    )
    assert sum(r.status_code == 429 for r in responses) == 5
    assert all(r.status_code in {201, 401, 429} for r in responses)


def test_concurrent_admin_demotion_preserves_one_enabled_admin(apps):
    first, aid = client_for(apps[0], "first-admin", admin=True)
    second, bid = client_for(apps[1], "second-admin", admin=True)
    responses = concurrently(
        [
            lambda: first.patch(f"/api/v3/admin/users/{aid}", json={"role": "member"}),
            lambda: second.patch(f"/api/v3/admin/users/{bid}", json={"enabled": False}),
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    with apps[0].state.database.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "admin", User.enabled.is_(True))
            )
            == 1
        )


def test_temporary_password_cannot_establish_two_concurrent_sessions(apps):
    admin, _ = client_for(apps[0], "admin", admin=True)
    _, uid = client_for(apps[0])
    temporary = admin.post(f"/api/v3/admin/users/{uid}:reset-password").json()["temporary_password"]
    clients = [TestClient(app, headers={"Origin": "http://testserver"}) for app in apps]
    responses = concurrently(
        [
            lambda client=client: client.post(
                "/api/v3/auth/login", json={"username": "alice", "password": temporary}
            )
            for client in clients
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 401]


def test_password_reset_revokes_a_login_that_was_already_verifying(apps, monkeypatch):
    """Reset must lock the user before revoking credentials created by an in-flight login."""
    from threading import Event

    from crashcap_api import routes_auth

    admin, _ = client_for(apps[0], "admin", admin=True)
    _, uid = client_for(apps[0])
    login_locked, reset_revoked = Event(), Event()
    verify = routes_auth.verify_password
    revoke = routes_auth.revoke_all

    def verify_while_reset_starts(*args):
        valid = verify(*args)
        login_locked.set()
        # With proper user locking, reset cannot revoke until this login commits.
        reset_revoked.wait(timeout=0.3)
        return valid

    def record_revocation(*args):
        revoke(*args)
        reset_revoked.set()

    monkeypatch.setattr(routes_auth, "verify_password", verify_while_reset_starts)
    monkeypatch.setattr(routes_auth, "revoke_all", record_revocation)
    signing_in = TestClient(apps[1], headers={"Origin": "http://testserver"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        login = pool.submit(
            signing_in.post, "/api/v3/auth/login", json={"username": "alice", "password": PASSWORD}
        )
        assert login_locked.wait(timeout=5)
        reset = pool.submit(admin.post, f"/api/v3/admin/users/{uid}:reset-password")
        assert login.result(timeout=10).status_code == 200
        assert reset.result(timeout=10).status_code == 200
    assert signing_in.get("/api/v3/auth/me").status_code == 401
