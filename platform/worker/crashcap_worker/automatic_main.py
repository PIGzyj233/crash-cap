from __future__ import annotations

import logging
import os
import socket
import time

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.ids import new_ulid
from crashcap_api.models import utcnow
from crashcap_api.redaction import configure_logging
from crashcap_api.services.analysis_demands import fanout_next
from crashcap_api.services.analysis_recovery import recover_expired_frozen_runs
from crashcap_api.storage import create_object_store

from .automatic_analysis import AutomaticAnalysisPlanner
from .core_runner import CoreExecutor

LOGGER = logging.getLogger(__name__)


def run() -> None:
    """Run catalog fanout and expensive automatic planning outside the outbox relay."""

    settings = Settings()
    configure_logging(settings.log_level)
    if not settings.automatic_analysis_enabled:
        LOGGER.info("automatic analysis is disabled")
        return
    database = Database(settings)
    owner_id = os.getenv(
        "CRASHCAP_AUTOMATIC_ANALYSIS_OWNER_ID",
        f"automatic-{socket.gethostname()}-{new_ulid()}",
    )
    planner = AutomaticAnalysisPlanner(
        settings,
        database.sessions,
        create_object_store(settings),
        CoreExecutor(settings),
    )
    pause_reported = False
    try:
        while True:
            handled = 0
            fanout_progress = False
            try:
                with database.sessions.begin() as session:
                    recover_expired_frozen_runs(session, settings, now=utcnow())
                if settings.automatic_analysis_paused and not pause_reported:
                    LOGGER.info("automatic analysis paused; recovery remains active")
                    pause_reported = True
                if not settings.automatic_analysis_paused:
                    with database.sessions.begin() as session:
                        page = fanout_next(session, now=utcnow())
                    handled = planner.run_once(owner_id=owner_id)
                    fanout_progress = bool(page.affected) or not page.caught_up
            except Exception:
                LOGGER.exception("automatic analysis iteration failed")
                fanout_progress = False
            if not handled and not fanout_progress:
                time.sleep(settings.relay_poll_seconds)
    finally:
        database.dispose()


if __name__ == "__main__":
    run()
