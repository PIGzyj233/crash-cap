"""Two browser actions around the independently consumed native role-change job."""

import json
import os
import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from crashcap_api.app import create_app


@contextmanager
def role_browser(settings, live, workspace_id, occurrence_id, old_run_id):
    if os.environ.get("CRASHCAP_QA_ROLE_BROWSER") != "1":
        yield None
        return
    app = create_app(settings.model_copy(update={"cors_origins": ("http://127.0.0.1:5189",)}))
    output = live["output"]
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
                    raise RuntimeError("Role browser API did not start")
                time.sleep(0.1)

            def wait_for_browser(stage, candidate_run_id=None):
                done = output / f"role-browser-{stage}.done"
                ready = {
                    "api_url": f"http://127.0.0.1:{port}",
                    "workspace_id": workspace_id,
                    "occurrence_id": occurrence_id,
                    "current_run_id": old_run_id,
                    "candidate_run_id": candidate_run_id,
                    "stage": stage,
                    "done_file": str(done),
                    "application_database_touched": False,
                }
                (output / "role-browser-ready.json").write_text(
                    json.dumps(ready, indent=2), encoding="utf-8"
                )
                deadline = time.monotonic() + 1500
                while not done.exists():
                    if not thread.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError(f"Role browser {stage} was not completed")
                    time.sleep(0.5)

            yield wait_for_browser
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            app.state.dispatcher.broker.close()
