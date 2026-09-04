"""Interactive browser checkpoint inside the owned native C20 qualification."""

import json
import socket
import threading
import time

import uvicorn
from crashcap_api.app import create_app
from crashcap_api.models import AnalysisDemandRestart
from fastapi.responses import JSONResponse
from sqlalchemy import select


def run_browser_restart(settings, live, workspace_id, occurrence_id, demand_id):
    app = create_app(
        settings.model_copy(
            update={
                "cors_origins": ("http://127.0.0.1:5189",),
            }
        )
    )
    requests = []

    @app.middleware("http")
    async def lose_first_response(request, call_next):
        response = await call_next(request)
        if request.method == "POST" and request.url.path.endswith("/analysis-demand/restarts"):
            requests.append(response.status_code)
            if response.status_code == 202 and len(requests) == 1:
                return JSONResponse(
                    {
                        "error": {
                            "code": "TEST_RESPONSE_LOST",
                            "message": "隔离验收：提交后响应丢失",
                        }
                    },
                    status_code=503,
                    headers={"Access-Control-Allow-Origin": "http://127.0.0.1:5189"},
                )
        return response

    output = live["output"]
    done = output / "browser.done"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 20
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.1)
            ready = {
                "api_url": f"http://127.0.0.1:{listener.getsockname()[1]}",
                "workspace_id": workspace_id,
                "occurrence_id": occurrence_id,
                "done_file": str(done),
                "application_database_touched": False,
            }
            (output / "browser-ready.json").write_text(json.dumps(ready), encoding="utf-8")
            deadline = time.monotonic() + 1800
            while not done.exists():
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.5)
            assert requests == [202, 202], requests
            with live["sessions"]() as session:
                rows = list(
                    session.scalars(
                        select(AnalysisDemandRestart).where(
                            AnalysisDemandRestart.demand_id == demand_id,
                        )
                    )
                )
                assert len(rows) == 1
                body, response = rows[0].request, rows[0].response
            (output / "browser-result.json").write_text(
                json.dumps(
                    {
                        **ready,
                        "status": "PASS",
                        "server_statuses": requests,
                        "request": body,
                        "response": response,
                        "response_loss_injected": True,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return body, response
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            app.state.dispatcher.broker.close()
