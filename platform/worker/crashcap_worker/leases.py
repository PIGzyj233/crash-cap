from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from crashcap_api.config import Settings
from crashcap_api.task_handoff import TaskClaim, claim_is_current, heartbeat_claim
from sqlalchemy.orm import Session, sessionmaker

LOGGER = logging.getLogger(__name__)


@contextmanager
def renewable_lease(
    sessions: sessionmaker[Session], settings: Settings, claim: TaskClaim
) -> Iterator[None]:
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(min(30, settings.task_lease_seconds / 3)):
            try:
                with sessions.begin() as session:
                    if not claim_is_current(session, claim):
                        return
                    heartbeat_claim(session, claim, lease_seconds=settings.task_lease_seconds)
            except Exception:
                LOGGER.exception("Symbol import heartbeat failed attempt_id=%s", claim.attempt_id)
                return  # Final transaction will reject expiry or a newer owner.

    thread = threading.Thread(target=renew, name="symbol-import-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
