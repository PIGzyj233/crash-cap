from __future__ import annotations

from typing import Any

import dramatiq

from .runtime import processor


@dramatiq.actor(queue_name="verify", max_retries=5, min_backoff=5_000, time_limit=900_000)
def verify_upload(message: dict[str, Any]) -> None:
    processor().verify_upload(message)


@dramatiq.actor(queue_name="ingest", max_retries=3, min_backoff=10_000, time_limit=900_000)
def ingest_artifact(message: dict[str, Any]) -> None:
    processor().ingest_artifact(message)


@dramatiq.actor(queue_name="ingest", max_retries=3, min_backoff=10_000, time_limit=900_000)
def reindex_symbols(message: dict[str, Any]) -> None:
    processor().reindex_symbols(message)


@dramatiq.actor(queue_name="dump-small", max_retries=2, min_backoff=15_000, time_limit=660_000)
def analyze_small(message: dict[str, Any]) -> None:
    processor().analyze_occurrence(message)


@dramatiq.actor(queue_name="dump-large", max_retries=2, min_backoff=30_000, time_limit=1_260_000)
def analyze_large(message: dict[str, Any]) -> None:
    processor().analyze_occurrence(message)
