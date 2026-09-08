"""F073 regression: controlled HTTP failures around the packaged heartbeat app."""

from fastapi import Request
from fastapi.responses import JSONResponse

from verification.m3fp.scenario_app import create_scenario_app as heartbeat_app


def create_scenario_app():
    app = heartbeat_app()
    failures = {"spend_table": (429, 1)}
    calls = {}

    @app.middleware("http")
    async def transient_failure(request: Request, call_next):
        path = request.url.path
        if path == "/v1/rack/query":
            path = request.query_params.get("resource", path)
        if path == "/__scenario__/failure":
            if request.method == "POST":
                failures["/v1/curation"] = (503, 1)
            return JSONResponse(calls)
        calls[path] = calls.get(path, 0) + 1
        status, remaining = failures.get(path, (200, 0))
        if remaining:
            failures[path] = (status, remaining - 1)
            return JSONResponse(
                {"detail": "The Palace is busy, retrying." if status == 429
                 else "The Palace is unavailable. Try again."},
                status_code=status,
                headers={"Retry-After": "5"},
            )
        return await call_next(request)

    return app
