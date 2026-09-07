from __future__ import annotations

import os

import uvicorn

from .app import create_app

app = create_app()


def run() -> None:
    uvicorn.run(
        "crashcap_api.main:app",
        host="0.0.0.0",  # noqa: S104 - container bind; publish boundary is validated separately
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=bool(app.state.settings.trusted_proxy_ips),
        forwarded_allow_ips=list(app.state.settings.trusted_proxy_ips),
        server_header=False,
    )


if __name__ == "__main__":
    run()
