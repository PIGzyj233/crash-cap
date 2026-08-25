from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from .config import Settings
from .contracts import validate_task_message

TaskHandler = Callable[[dict[str, Any]], None]


class TaskDispatcher(Protocol):
    def enqueue(self, message: dict[str, Any]) -> None: ...


class MemoryTaskDispatcher:
    """Deterministic explicit test double with drain/restart snapshots."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.messages: deque[dict[str, Any]] = deque()
        self.handlers: dict[str, TaskHandler] = {}

    def register(self, task_type: str, handler: TaskHandler) -> None:
        self.handlers[task_type] = handler

    def enqueue(self, message: dict[str, Any]) -> None:
        validate_task_message(message, self.settings.schema_root)
        if message.get("queue") == "dump-huge":
            raise ValueError("Phase 1 must never enqueue dump-huge")
        self.messages.append(dict(message))

    def drain(self, limit: int = 1000) -> int:
        handled = 0
        while self.messages and handled < limit:
            message = self.messages.popleft()
            handler = self.handlers.get(str(message["task_type"]))
            if handler is None:
                raise RuntimeError(f"no in-memory handler for {message['task_type']}")
            handler(message)
            handled += 1
        return handled

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def restore(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            self.enqueue(message)


class DramatiqTaskDispatcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
        dramatiq.set_broker(broker)
        self.broker = broker

    def enqueue(self, message: dict[str, Any]) -> None:
        validate_task_message(message, self.settings.schema_root)
        if message.get("queue") == "dump-huge":
            raise ValueError("Phase 1 must never enqueue dump-huge")
        from crashcap_worker import tasks

        task_type = message["task_type"]
        if task_type == "verify_upload":
            tasks.verify_upload.send(message)
        elif task_type == "ingest_artifact":
            tasks.ingest_artifact.send(message)
        elif task_type == "publish_artifact_blob_pair":
            tasks.publish_artifact_blob_pair.send(message)
        elif task_type == "reindex_symbols":
            tasks.reindex_symbols.send(message)
        elif task_type == "analyze_occurrence":
            if message["queue"] == "dump-small":
                tasks.analyze_small.send(message)
            elif message["queue"] == "dump-large":
                tasks.analyze_large.send(message)
            else:
                raise ValueError("unsupported analysis queue")
        else:
            raise ValueError(f"unsupported task type: {task_type}")


def publish_task(dispatcher: TaskDispatcher, message: dict[str, Any]) -> None:
    """The single low-level publish seam used by relay and legacy compatibility."""

    dispatcher.enqueue(message)


def create_dispatcher(settings: Settings) -> TaskDispatcher:
    if settings.queue_mode == "memory":
        if settings.environment != "test":
            raise ValueError("memory queue is restricted to explicit test settings")
        return MemoryTaskDispatcher(settings)
    return DramatiqTaskDispatcher(settings)
