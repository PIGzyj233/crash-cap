from __future__ import annotations

import logging
import os
import time

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.redaction import configure_logging
from crashcap_api.storage import create_object_store

from .retention import expire_dump_blobs

LOGGER = logging.getLogger(__name__)


def run() -> None:
    """Run the production retention sweep on a fixed, deployment-owned cadence."""

    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    store = create_object_store(settings)
    interval = max(60, int(os.getenv("CRASHCAP_RETENTION_INTERVAL_SECONDS", "86400")))
    limit = max(1, int(os.getenv("CRASHCAP_RETENTION_BATCH_SIZE", "1000")))
    while True:
        try:
            expired = expire_dump_blobs(database.sessions, store, limit=limit)
            LOGGER.info("retention sweep completed expired_raw_dump_blobs=%d", expired)
        except Exception:
            LOGGER.exception("retention sweep failed")
        time.sleep(interval)


if __name__ == "__main__":
    run()
