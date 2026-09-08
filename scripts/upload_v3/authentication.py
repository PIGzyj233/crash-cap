"""Short-lived, interactive credentials for the deployment acceptance runner."""

from __future__ import annotations

import getpass
import json
import urllib.error
import urllib.request
import warnings
from contextlib import contextmanager
from http.cookiejar import CookieJar
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def authenticated_api(base_url, origin, username):
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "API URL must not contain credentials, query data or a fragment"
        )
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()), NoRedirect()
    )
    csrf = None

    def api(path, body=None, *, method=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Expected a relative API path")
        headers = {"Content-Type": "application/json", "Origin": origin}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        with opener.open(request, timeout=30) as response:
            return None if response.status == 204 else json.load(response)

    login = api(
        "/auth/login", {"username": username, "password": getpass.getpass("平台密码: ")}
    )
    csrf = login["csrf_token"]
    issued = None
    try:
        if login["user"]["must_change_password"]:
            raise ValueError(
                "Set a permanent password in the browser before running acceptance"
            )
        issued = api(
            "/me/tokens", {"name": "deployment-acceptance", "expires_in_days": 1}
        )
        yield api, issued["token"]
    finally:
        try:
            if issued:
                api(f"/me/tokens/{issued['id']}:revoke", method="POST")
        except (urllib.error.URLError, OSError):
            warnings.warn(
                "Acceptance token could not be revoked; revoke it on the account page",
                stacklevel=2,
            )
        finally:
            try:
                api("/auth/logout", method="POST")
            except (urllib.error.URLError, OSError):
                warnings.warn("Acceptance session logout failed", stacklevel=2)
