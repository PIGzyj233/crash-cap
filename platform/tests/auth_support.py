"""Authenticated business-test client; authentication tests use the raw TestClient."""

import uuid

from fastapi.testclient import TestClient


class AuthenticatedClient(TestClient):
    def __enter__(self):
        super().__enter__()
        self.headers["Origin"] = self.app.state.settings.auth_origin
        name = "test-" + uuid.uuid4().hex
        password = "test password unique enough"  # noqa: S105 - test-only credential
        created = self.post(
            "/api/v3/auth/register",
            json={"username": name, "display_name": "Test User", "password": password},
        )
        assert created.status_code == 201, created.text
        logged_in = self.post("/api/v3/auth/login", json={"username": name, "password": password})
        assert logged_in.status_code == 200, logged_in.text
        self.headers["X-CSRF-Token"] = logged_in.json()["csrf_token"]
        self.user_id = logged_in.json()["user"]["id"]
        return self
