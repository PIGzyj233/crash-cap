from __future__ import annotations

import logging
import os
import time

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.redaction import configure_logging
from crashcap_api.storage import create_object_store
from prometheus_client import start_http_server

from .retention import expire_dump_blobs, sweep_upload_payloads

LOGGER = logging.getLogger(__name__)


def run() -> None:
    """Run the production retention sweep on a fixed, deployment-owned cadence."""

    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    store = create_object_store(settings)
    metrics_bind = os.getenv("CRASHCAP_RETENTION_METRICS_BIND", "127.0.0.1")
    metrics_port = int(os.getenv("CRASHCAP_RETENTION_METRICS_PORT", "9109"))
    start_http_server(metrics_port, addr=metrics_bind)
    LOGGER.info("retention metrics listening bind=%s port=%d", metrics_bind, metrics_port)
    interval = max(60, int(os.getenv("CRASHCAP_RETENTION_INTERVAL_SECONDS", "86400")))
    limit = max(1, int(os.getenv("CRASHCAP_RETENTION_BATCH_SIZE", "1000")))
    while True:
        try:
            expired = expire_dump_blobs(database.sessions, store, limit=limit)
            uploads = sweep_upload_payloads(database.sessions, store, settings, limit=limit)
            LOGGER.info(
                "retention sweep completed expired_raw_dump_blobs=%d upload_gc_mode=%s "
                "upload_gc_deleted=%d upload_gc_would_delete=%d upload_gc_failed=%d",
                expired,
                uploads["mode"],
                uploads["deleted"],
                uploads["would_delete"],
                uploads["failed"],
            )
        except Exception:
            LOGGER.exception("retention sweep failed")
        time.sleep(interval)


if __name__ == "__main__":
    run()
