"""Optional browser observation of the real expired-DMP qualification state."""

import json
import socket
import threading
import time

import uvicorn
from crashcap_api.app import create_app
from crashcap_api.models import AnalysisRun, Occurrence
from sqlalchemy import select


def observe_expired_reports(settings, live, previous, statuses):
    app = create_app(settings.model_copy(update={"cors_origins": ("http://127.0.0.1:5189",)}))
    output = live["output"]
    done = output / "expiry-browser.done"
    with live["sessions"]() as session:
        runs = set(session.scalars(select(AnalysisRun.id)))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 20
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Expiry browser API did not start")
                time.sleep(0.1)
            ready = {
                "api_url": f"http://127.0.0.1:{port}",
                "reports": [
                    {
                        "workspace_id": wid,
                        "occurrence_id": oid,
                        "current_run_id": rid,
                        "canonical_sha256": digest,
                        "demand": statuses[oid],
                    }
                    for oid, (wid, rid, _, digest) in previous.items()
                ],
                "done_file": str(done),
                "application_database_touched": False,
            }
            (output / "expiry-browser-ready.json").write_text(
                json.dumps(ready, indent=2), encoding="utf-8"
            )
            deadline = time.monotonic() + 3300
            while not done.exists():
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Expiry browser observation was not completed")
                time.sleep(0.5)
            with live["sessions"]() as session:
                assert set(session.scalars(select(AnalysisRun.id))) == runs
                for oid, (_, rid, _, _) in previous.items():
                    assert session.get(Occurrence, oid).current_run_id == rid
            (output / "expiry-browser-result.json").write_text(
                json.dumps(ready, indent=2), encoding="utf-8"
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            app.state.dispatcher.broker.close()
