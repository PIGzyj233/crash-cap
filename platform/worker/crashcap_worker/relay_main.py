from __future__ import annotations

import logging
import os
import socket
import time

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.ids import new_ulid
from crashcap_api.queueing import create_dispatcher
from crashcap_api.redaction import configure_logging

from .outbox_relay import relay_once

LOGGER = logging.getLogger(__name__)


def run() -> None:
    """Continuously relay committed task intents without owning domain writes."""

    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    dispatcher = create_dispatcher(settings)
    owner_id = os.getenv(
        "CRASHCAP_RELAY_OWNER_ID",
        f"relay-{socket.gethostname()}-{new_ulid()}",
    )
    try:
        while True:
            try:
                handled = relay_once(
                    database.sessions,
                    dispatcher,
                    settings,
                    owner_id=owner_id,
                )
            except Exception:
                LOGGER.exception("outbox relay iteration failed")
                handled = False
            if not handled:
                time.sleep(settings.relay_poll_seconds)
    finally:
        database.dispose()


if __name__ == "__main__":
    run()
