"""Pinned, disposable Symbolicator used only by the local browser harness."""

import json
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
from owned_browser_storage import docker

IMAGE = "ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"


@contextmanager
def owned_symbolicator(output):
    output.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    config = output / "symbolicator.yml"
    config.write_text(
        "bind: 0.0.0.0:3021\ncache_dir: /data\nconnect_to_reserved_ips: true\n"
        "max_concurrent_requests: 4\nsources: []\n",
        encoding="utf-8",
    )
    container = docker(
        "run",
        "--pull=never",
        "-d",
        "--name",
        "qai-browser-symbolicator-" + token,
        "--label",
        "crashcap.qai.browser-symbolicator=" + token,
        "-p",
        "127.0.0.1::3021",
        "--mount",
        f"type=bind,source={config.resolve().as_posix()},target=/etc/symbolicator/config.yml,readonly",
        "-v",
        "/data",
        IMAGE,
        "run",
        "-c",
        "/etc/symbolicator/config.yml",
    )
    receipt = {"container_id": container, "owner_token": token, "removed": False}
    path = output / "symbolicator.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    try:
        mapping = docker("port", container, "3021/tcp")
        assert mapping.startswith("127.0.0.1:")
        endpoint = "http://" + mapping
        for _ in range(100):
            try:
                if httpx.get(endpoint + "/healthcheck", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Owned Symbolicator did not start")
        image_id = docker("inspect", "--format", "{{.Image}}", container)
        version = (
            docker("exec", container, "symbolicator", "--version")
            .splitlines()[0]
            .removeprefix("symbolicator version: ")
        )
        assert version == "26.7.2"
        receipt.update(endpoint=endpoint, image_id=image_id, version=version)
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        yield receipt
    finally:
        assert (
            docker(
                "inspect",
                container,
                "--format",
                '{{index .Config.Labels "crashcap.qai.browser-symbolicator"}}',
            )
            == token
        )
        docker("rm", "-f", "-v", container)
        receipt["removed"] = True
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
