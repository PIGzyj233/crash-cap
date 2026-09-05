"""Explicit interactive qualification using the native test's disposable PostgreSQL."""

import json
import os
import socket
import threading
import time

import uvicorn
from crashcap_api.app import create_app
from crashcap_api.models import CurrentDecision, Occurrence, ResultReview
from fastapi.responses import JSONResponse
from sqlalchemy import select


def run_browser_review(
    settings, live, workspace_id, occurrence_id, old_run_id, run_id, *, decision="promote"
):
    selected = settings.model_copy(update={"cors_origins": ("http://127.0.0.1:5189",)})
    app = create_app(selected)
    drop_response = os.environ.get("CRASHCAP_QA_REVIEW_DROP_RESPONSE") == "1"
    dropped = False

    @app.middleware("http")
    async def lose_first_review_response(request, call_next):
        nonlocal dropped
        response = await call_next(request)
        if (
            drop_response
            and not dropped
            and request.method == "POST"
            and request.url.path.endswith("/result-reviews")
            and response.status_code == 200
        ):
            dropped = True
            return JSONResponse(
                {"error": {"code": "TEST_RESPONSE_LOST", "message": "隔离验收：提交后响应丢失"}},
                status_code=503,
                headers={"Access-Control-Allow-Origin": "http://127.0.0.1:5189"},
            )
        return response

    output = live["output"]
    done = output / "browser.done"
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
                    raise RuntimeError("Browser API did not start")
                time.sleep(0.1)
            ready = {
                "api_url": f"http://127.0.0.1:{port}",
                "workspace_id": workspace_id,
                "occurrence_id": occurrence_id,
                "current_run_id": old_run_id,
                "candidate_run_id": run_id,
                "expected_decision": decision,
                "done_file": str(done),
                "application_database_touched": False,
            }
            (output / "browser-ready.json").write_text(
                json.dumps(ready, indent=2), encoding="utf-8"
            )
            deadline = time.monotonic() + 3300
            while not done.exists():
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Browser qualification was not completed")
                time.sleep(0.5)
            with live["sessions"]() as session:
                reviews = list(
                    session.scalars(
                        select(ResultReview).where(ResultReview.occurrence_id == occurrence_id)
                    )
                )
                assert len(reviews) == 1
                assert reviews[0].current_run_id == old_run_id
                assert reviews[0].candidate_run_id == run_id
                assert reviews[0].decision == decision
                assert session.get(Occurrence, occurrence_id).current_run_id == run_id
                assert session.get(CurrentDecision, run_id).decision == "incomparable"
                ready["review_id"] = reviews[0].id
                ready["audit_sha256"] = reviews[0].audit_sha256
                ready["response_loss_injected"] = dropped
                if drop_response:
                    assert dropped
            (output / "browser-result.json").write_text(
                json.dumps(ready, indent=2), encoding="utf-8"
            )
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            app.state.dispatcher.broker.close()
