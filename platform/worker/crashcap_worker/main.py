from __future__ import annotations

import os
import sys

PHASE1_QUEUES = {"verify", "ingest", "dump-small", "dump-large"}


def worker_arguments() -> list[str]:
    configured = os.getenv("CRASHCAP_WORKER_QUEUES", "verify,ingest,dump-small,dump-large")
    queues = [queue.strip() for queue in configured.split(",") if queue.strip()]
    if not queues or any(queue not in PHASE1_QUEUES for queue in queues):
        raise ValueError("CRASHCAP_WORKER_QUEUES must contain only Phase 1 queues")
    processes = max(1, int(os.getenv("CRASHCAP_WORKER_PROCESSES", "1")))
    threads = max(1, int(os.getenv("CRASHCAP_WORKER_THREADS", "1")))
    return [
        sys.executable,
        "-m",
        "dramatiq",
        "crashcap_worker.broker:configure_broker",
        "crashcap_worker.tasks",
        "--queues",
        *queues,
        "--processes",
        str(processes),
        "--threads",
        str(threads),
    ]


def run() -> None:
    """Start Dramatiq with every Phase 1 queue explicitly declared."""

    arguments = worker_arguments()
    os.execv(sys.executable, arguments)  # noqa: S606 - replace worker process intentionally


if __name__ == "__main__":
    run()
