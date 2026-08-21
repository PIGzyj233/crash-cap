from __future__ import annotations

from functools import lru_cache

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.queueing import DramatiqTaskDispatcher
from crashcap_api.storage import create_object_store

from .processor import WorkerProcessor


@lru_cache(maxsize=1)
def processor() -> WorkerProcessor:
    settings = Settings()
    database = Database(settings)
    database.assert_supported_postgres()
    store = create_object_store(settings)
    dispatcher = DramatiqTaskDispatcher(settings)
    return WorkerProcessor(settings, database.sessions, store, dispatcher)
