"""Serve an actual C08/C09 report for explicit browser observation."""

import hashlib
import json
import socket
import threading
import time

import uvicorn
from crashcap_api.app import create_app
from crashcap_api.models import AnalysisRun, Occurrence
from sqlalchemy import select


def observe_report(settings, live, canonical, raw, case):
    app = create_app(settings.model_copy(update={"cors_origins": ("http://127.0.0.1:5189",)}))
    done = live["output"] / "cross-module-browser.done"
    with live["sessions"]() as session:
        run_ids = set(session.scalars(select(AnalysisRun.id)))
        current = session.get(Occurrence, canonical["occurrence_id"]).current_run_id
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 20
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Cross-module browser API did not start")
                time.sleep(0.1)
            ready = {
                "case": case,
                "api_url": f"http://127.0.0.1:{listener.getsockname()[1]}",
                "workspace_id": canonical["workspace_id"],
                "occurrence_id": canonical["occurrence_id"],
                "current_run_id": current,
                "canonical_sha256": hashlib.sha256(raw).hexdigest(),
                "done_file": str(done),
            }
            (live["output"] / "cross-module-browser-ready.json").write_text(
                json.dumps(ready, indent=2), encoding="utf-8"
            )
            deadline = time.monotonic() + 1500
            while not done.exists():
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Cross-module browser observation incomplete")
                time.sleep(0.5)
            with live["sessions"]() as session:
                assert set(session.scalars(select(AnalysisRun.id))) == run_ids
                assert session.get(Occurrence, canonical["occurrence_id"]).current_run_id == current
                run = session.get(AnalysisRun, current)
                assert b"".join(live["store"].stream(run.result_object_key)) == raw
            (live["output"] / "cross-module-browser-result.json").write_text(
                json.dumps({**ready, "status": "PASS"}, indent=2), encoding="utf-8"
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            app.state.dispatcher.broker.close()
