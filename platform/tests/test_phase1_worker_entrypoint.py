from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Any

import dramatiq
from crashcap_worker import broker as broker_module
from crashcap_worker import main as worker_main


def test_worker_broker_uses_configured_redis_url(monkeypatch: Any) -> None:
    configured: dict[str, object] = {}
    fake_broker = object()

    monkeypatch.setattr(
        broker_module,
        "Settings",
        lambda: SimpleNamespace(redis_url="redis://redis.internal:6379/4"),
    )

    def create_broker(*, url: str) -> object:
        configured["url"] = url
        return fake_broker

    monkeypatch.setattr(broker_module, "RedisBroker", create_broker)
    monkeypatch.setattr(dramatiq, "set_broker", lambda value: configured.update(broker=value))

    assert broker_module.configure_broker() is fake_broker
    assert configured == {
        "url": "redis://redis.internal:6379/4",
        "broker": fake_broker,
    }


def test_worker_entrypoint_configures_broker_before_importing_tasks(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def capture_execv(executable: str, arguments: list[str]) -> None:
        captured.update(executable=executable, arguments=arguments)

    monkeypatch.setattr(os, "execv", capture_execv)

    worker_main.run()

    assert captured["executable"] == sys.executable
    arguments = captured["arguments"]
    assert isinstance(arguments, list)
    assert arguments.index("crashcap_worker.broker:configure_broker") < arguments.index(
        "crashcap_worker.tasks"
    )
