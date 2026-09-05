"""A new empty Symbolicator cache backed exclusively by restored storage."""

import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager

import httpx
import uvicorn
from crashcap_api.db import Database
from crashcap_api.storage import create_object_store
from crashcap_api.symbol_source import create_symbol_source_app

from .catalog_restore import docker


@contextmanager
def restored_symbolicator(settings, live, receipt):
    database = Database(settings)
    store = create_object_store(settings)
    app = create_symbol_source_app(settings, database=database, store=store)
    events = []

    @app.middleware("http")
    async def observe(request, call_next):
        response = await call_next(request)
        events.append({"path": request.url.path, "status": response.status_code})
        return response

    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))  # noqa: S104 - isolated fixture endpoint for Docker
    listener.listen(64)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    container = None
    token = uuid.uuid4().hex
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(0.05)
        config = (live["output"] / "symbolicator.yml").resolve().as_posix()
        container = docker(
            "run",
            "--pull=never",
            "-d",
            "--name",
            "qai-restored-symbols-" + token,
            "--label",
            "crashcap.qai.restored.symbols=" + token,
            "--label",
            "crashcap.qai.material.run=" + os.environ["QAI_MATERIAL_RUN_TOKEN"],
            "-p",
            "127.0.0.1::3021",
            *(["--add-host", "host.docker.internal:host-gateway"] if os.name != "nt" else []),
            "--mount",
            f"type=bind,source={config},target=/etc/symbolicator/config.yml,readonly",
            "-v",
            "/data",
            live["image_id"],
            "run",
            "-c",
            "/etc/symbolicator/config.yml",
        )
        endpoint = "http://" + docker("port", container, "3021/tcp")
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(endpoint + "/healthcheck", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline
            time.sleep(0.1)
        assert not events, "New Symbolicator must not start with restored cache requests"
        receipt["fresh_symbolicator_container"] = container
        receipt["fresh_cache_volume"] = docker(
            "inspect",
            "--format",
            '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}',
            container,
        )
        yield (
            settings.model_copy(
                update={
                    "frozen_core_enabled": True,
                    "core_image_digest": "sha256:" + "0" * 64,
                    "frozen_allow_local_core_sentinel": True,
                    "frozen_symbolicator_url": endpoint,
                    "frozen_pair_source_root": f"http://host.docker.internal:{port}/v2/pairs",
                    "frozen_symbolicator_image_digest": live["image_id"],
                    "symbolicator_version": live["version"],
                }
            ),
            database.sessions,
            store,
            events,
        )
    finally:
        if container is not None:
            assert (
                docker(
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "crashcap.qai.restored.symbols"}}',
                    container,
                )
                == token
            )
            docker("rm", "-f", "-v", container)
            receipt["fresh_symbolicator_and_volume_removed"] = True
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        database.dispose()
        receipt["restored_source_requests"] = events
        assert not thread.is_alive()
