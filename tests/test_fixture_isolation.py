"""A-038 reachability proofs for deterministic fixture servers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from verification.fixture_isolation import FixtureIsolationMiddleware, install_fixture_isolation
from verification.run_fixture import main as run_fixture


def fixture_app() -> FastAPI:
    app = FastAPI()
    install_fixture_isolation(app, "M2O REGRESSION")

    @app.get("/")
    async def root() -> dict[str, bool]:
        return {"fixture": True}

    return app


def test_fixture_refuses_owner_port_before_serving_ui() -> None:
    """B.6 rule 10: a fake is unreachable on the owner's product port."""

    client = TestClient(fixture_app(), base_url="http://127.0.0.1:8765")
    response = client.get("/")
    assert response.status_code == 409
    assert "FIXTURE REFUSED" in response.text


@pytest.mark.asyncio
async def test_fixture_refusal_uses_socket_port_not_spoofable_host() -> None:
    """A-038: a misleading Host header cannot bypass the product-port wall."""

    reached = False
    sent: list[dict[str, object]] = []

    async def inner(_scope: object, _receive: object, _send: object) -> None:
        nonlocal reached
        reached = True

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    wall = FixtureIsolationMiddleware(inner, fixture="M2O REGRESSION")
    await wall(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"127.0.0.1:8780")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8765),
        },
        receive,
        send,
    )
    assert reached is False
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 409


def test_fixture_redirects_to_server_verified_identity() -> None:
    """A-038: UI marker opt-in comes from the serving fixture, never a query alone."""

    client = TestClient(fixture_app(), base_url="http://127.0.0.1:8780")
    redirect = client.get("/", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/?fixture=M2O+REGRESSION"
    assert client.get("/__scenario__/identity").json() == {
        "fixture": "M2O REGRESSION",
        "deterministic": True,
    }


def test_fixture_launcher_rejects_owner_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """A-038: the standard foreground launcher cannot bind the owner port."""

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verification.run_fixture",
            "verification.m2o.scenario_app:create_scenario_app",
            "--port",
            "8765",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        run_fixture()
    assert raised.value.code == 2


def test_every_scenario_app_installs_the_shared_reachability_wall() -> None:
    """B.6 rule 10: no legacy fixture silently escapes the common isolation wall."""

    root = Path(__file__).parents[1] / "verification"
    scenario_files = sorted(root.glob("*/scenario_app.py"))
    assert scenario_files
    missing = [
        path.relative_to(root).as_posix()
        for path in scenario_files
        if "install_fixture_isolation(" not in path.read_text("utf-8")
    ]
    assert missing == []
