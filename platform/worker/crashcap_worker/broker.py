from __future__ import annotations

import dramatiq
from crashcap_api.config import Settings
from dramatiq.brokers.redis import RedisBroker


def configure_broker() -> RedisBroker:
    """Install the configured Redis broker before Dramatiq imports actors."""

    settings = Settings()
    broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
    dramatiq.set_broker(broker)
    return broker
