from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import dramatiq
from crashcap_api.errors import ApiError
from crashcap_api.task_handoff import TaskReceiptError, poison_task_delivery

from .processor import WorkerProcessor
from .runtime import processor

LOGGER = logging.getLogger(__name__)


def _consume(
    selected: WorkerProcessor,
    handler: Callable[[dict[str, Any]], None],
    message: dict[str, Any],
) -> None:
    try:
        handler(message)
    except (ApiError, TaskReceiptError) as error:
        with selected.sessions() as session:
            poisoned = poison_task_delivery(
                session,
                message,
                f"PERMANENT_{type(error).__name__.upper()}",
            )
            session.commit()
        LOGGER.error(
            "permanent task delivery rejected task_type=%s attempt_id=%s durable=%s error=%s",
            message.get("task_type"),
            message.get("attempt_id"),
            poisoned,
            type(error).__name__,
        )


@dramatiq.actor(queue_name="verify", max_retries=5, min_backoff=5_000, time_limit=900_000)
def verify_upload(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.verify_upload, message)


@dramatiq.actor(queue_name="ingest", max_retries=3, min_backoff=10_000, time_limit=900_000)
def ingest_artifact(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.ingest_artifact, message)


@dramatiq.actor(queue_name="ingest", max_retries=5, min_backoff=10_000, time_limit=900_000)
def publish_artifact_blob_pair(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.publish_artifact_blob_pair, message)


@dramatiq.actor(queue_name="ingest", max_retries=3, min_backoff=10_000, time_limit=900_000)
def reindex_symbols(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.reindex_symbols, message)


@dramatiq.actor(queue_name="dump-small", max_retries=2, min_backoff=15_000, time_limit=660_000)
def analyze_small(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.analyze_occurrence, message)


@dramatiq.actor(queue_name="ingest", max_retries=0, time_limit=7_200_000)
def verify_symbol_import_pair(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.verify_symbol_import_pair, message)


@dramatiq.actor(queue_name="ingest", max_retries=5, min_backoff=5_000, time_limit=900_000)
def dispatch_workspace_role(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.dispatch_workspace_role, message)


@dramatiq.actor(queue_name="dump-small", max_retries=2, min_backoff=15_000, time_limit=660_000)
def analyze_frozen_small(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.analyze_frozen_run, message)


@dramatiq.actor(queue_name="dump-large", max_retries=2, min_backoff=30_000, time_limit=1_260_000)
def analyze_frozen_large(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.analyze_frozen_run, message)


@dramatiq.actor(queue_name="dump-large", max_retries=2, min_backoff=30_000, time_limit=1_260_000)
def analyze_large(message: dict[str, Any]) -> None:
    selected = processor()
    _consume(selected, selected.analyze_occurrence, message)
