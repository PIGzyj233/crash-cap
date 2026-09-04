"""Loopback-only browser qualification harness with real Core, isolated SQLite/store."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import threading
import time
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_worker.outbox_relay import relay_once

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8197)
    parser.add_argument("--reviews", action="store_true", help="Enable provider review UI qualification")
    parser.add_argument(
        "--s3", action="store_true", help="Use disposable real loopback RustFS"
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="Run frozen native analysis and automatic updates",
    )
    args = parser.parse_args()
    run_dir = ROOT / "target/qa-symbol-import/import-browser" / uuid4().hex
    run_dir.mkdir(parents=True)
    settings = Settings.model_validate(
        Settings.for_test(run_dir)
        .model_copy(
            update={
                # API, planner and material source run concurrently. An in-memory
                # StaticPool would share one DBAPI connection across transactions.
                "database_url": "sqlite+pysqlite:///"
                + (run_dir / "browser.db").as_posix(),
                "symbol_imports_enabled": True,
                "catalog_reviews_enabled": args.reviews,
                "core_executor": "local",
                "core_command": str(ROOT / "target/debug/dmp-core.exe"),
                "task_handoff_mode": "outbox",
                "task_receipt_mode": "strict",
                "cors_origins": ("http://127.0.0.1:5189",),
            }
        )
        .model_dump()
    )
    with ExitStack() as resources:
        listener = None
        if args.s3:
            from owned_browser_storage import owned_storage

            overrides, _, _ = resources.enter_context(
                owned_storage(run_dir / "storage")
            )
            settings = Settings.model_validate({**settings.model_dump(), **overrides})
        if args.native:
            from owned_browser_symbolicator import owned_symbolicator

            native = resources.enter_context(owned_symbolicator(run_dir / "native"))
            listener = resources.enter_context(socket.socket())
            listener.bind(("0.0.0.0", 0))  # synthetic fixture source for Docker Desktop
            listener.listen(64)
            settings = Settings.model_validate(
                {
                    **settings.model_dump(),
                    "catalog_source_enabled": True,
                    "automatic_analysis_enabled": True,
                    "frozen_core_enabled": True,
                    "frozen_analysis_enabled": True,
                    "evidence_promotion_enabled": True,
                    "frozen_public_sources": [],
                    "core_image_digest": "sha256:" + "0" * 64,
                    "frozen_allow_local_core_sentinel": True,
                    "frozen_symbolicator_url": native["endpoint"],
                    "frozen_symbolicator_image_digest": native["image_id"],
                    "symbolicator_version": native["version"],
                    "frozen_pair_source_root": f"http://host.docker.internal:{listener.getsockname()[1]}/v2/pairs",
                }
            )
        serve(settings, run_dir, args.port, listener)


def serve(settings: Settings, run_dir: Path, port: int, listener=None) -> None:
    app = create_app(settings)
    original_lifespan = app.router.lifespan_context
    from crashcap_api.models import utcnow
    from crashcap_api.services.analysis_demands import fanout_next
    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
    from crashcap_worker.core_runner import CoreExecutor

    planner = AutomaticAnalysisPlanner(
        settings, app.state.database.sessions, app.state.store, CoreExecutor(settings)
    )

    def drain() -> None:
        if settings.automatic_analysis_enabled:
            with app.state.database.sessions.begin() as session:
                fanout_next(session, now=utcnow())
            planner.run_once(owner_id="browser-qualification-planner")
        relay_once(
            app.state.database.sessions,
            app.state.dispatcher,
            settings,
            owner_id="browser-qualification",
        )
        app.state.dispatcher.drain()

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            stopped = asyncio.Event()
            source_server = None
            source_thread = None
            if listener is not None:
                from crashcap_api.symbol_source import create_symbol_source_app

                source_app = create_symbol_source_app(
                    settings, database=app.state.database, store=app.state.store
                )
                source_server = uvicorn.Server(
                    uvicorn.Config(source_app, log_level="warning")
                )
                source_thread = threading.Thread(
                    target=lambda: source_server.run(sockets=[listener]), daemon=True
                )
                source_thread.start()
                deadline = time.monotonic() + 15
                while not source_server.started:
                    if not source_thread.is_alive() or time.monotonic() >= deadline:
                        raise RuntimeError("Browser material source did not start")
                    await asyncio.sleep(0.05)

            async def consume():
                while not stopped.is_set():
                    await asyncio.to_thread(drain)
                    try:
                        await asyncio.wait_for(stopped.wait(), timeout=0.5)
                    except TimeoutError:
                        pass

            task = asyncio.create_task(consume())
            try:
                yield
            finally:
                stopped.set()
                await task
                if source_server is not None:
                    source_server.should_exit = True
                    source_thread.join(timeout=10)

    app.router.lifespan_context = lifespan
    receipt = {
        "run_dir": str(run_dir),
        "application_database_touched": False,
        "database": "isolated file SQLite",
        "queue": "in-process outbox relay/worker",
        "core": settings.core_command,
        "url": f"http://127.0.0.1:{port}",
        "object_store": settings.object_store_backend,
        "automatic_native_analysis": settings.automatic_analysis_enabled,
    }
    (run_dir / "harness.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
