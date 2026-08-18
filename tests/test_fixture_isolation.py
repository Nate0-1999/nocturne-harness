"""A-038 reachability proofs for deterministic fixture servers."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse

from verification.fixture_isolation import FixtureIsolationMiddleware, install_fixture_isolation
from verification.run_fixture import main as run_fixture


def fixture_app() -> FastAPI:
    app = FastAPI()
    install_fixture_isolation(app, "M2O REGRESSION")

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return "<!doctype html><html><body><main>fixture body</main></body></html>"

    return app


def test_fixture_refuses_owner_port_before_serving_ui() -> None:
    """SPEC B.6 rule 10 makes every fake unreachable on the owner's product port."""

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


def test_fixture_wrapper_injects_an_unmistakable_packet_banner() -> None:
    """F052 and SPEC D.2 120 require the fixture server, not the SPA, to mark HTML."""

    client = TestClient(fixture_app(), base_url="http://127.0.0.1:8780")
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["x-nocturne-fixture"] == "M2O REGRESSION"
    assert response.headers["x-nocturne-fixture-packet"] == "M2O"
    assert 'id="nocturne-fixture-curtain"' in response.text
    assert 'data-fixture="M2O REGRESSION"' in response.text
    assert 'data-packet-id="M2O"' in response.text
    assert "FIXTURE · M2O REGRESSION · PACKET M2O · NOT THE OWNER APP" in response.text
    assert response.text.index("fixture body") < response.text.index("nocturne-fixture-curtain")


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


def test_every_fixture_server_installs_the_shared_curtain() -> None:
    """F052 and SPEC D.2 120 keep every verification FastAPI behind one curtain."""

    root = Path(__file__).parents[1] / "verification"
    fixture_servers = sorted(
        {
            *root.glob("*/scenario_app.py"),
            *(
                path
                for path in root.rglob("*.py")
                if "FastAPI(" in path.read_text("utf-8")
                and path.name != "fixture_isolation.py"
            ),
        }
    )
    assert fixture_servers
    missing = [
        path.relative_to(root).as_posix()
        for path in fixture_servers
        if "install_fixture_isolation(" not in path.read_text("utf-8")
    ]
    assert missing == []


def test_scenario_class_has_no_browser_auto_open_path() -> None:
    """F052 and SPEC D.2 120 forbid scenario servers from opening owner-visible windows."""

    root = Path(__file__).parents[1] / "verification"
    sources = sorted(root.glob("*/scenario_app.py")) + [root / "run_fixture.py"]
    forbidden = ("webbrowser", "open_new(", "open_new_tab(", "startfile(", "osascript")
    violations = [
        f"{path.relative_to(root)}:{marker}"
        for path in sources
        for marker in forbidden
        if marker in path.read_text("utf-8")
    ]
    assert violations == []


def test_verification_browser_launches_are_explicitly_headless_without_fallback() -> None:
    """F052 and SPEC D.2 120 require every verification browser launch to stay headless."""

    root = Path(__file__).parents[1] / "verification"
    launch_pattern = re.compile(r"(?:chromium|firefox|webkit)\.launch(?:PersistentContext)?\(")
    headless_true = re.compile(r"headless\s*[:=]\s*(?:true|True)")
    headed_value = re.compile(
        r"headless\s*[:=]\s*(?:false\b|False\b|process\.env|os\.environ|getenv\()"
    )
    browser_sources = sorted((*root.rglob("*.mjs"), *root.rglob("*.js"), *root.rglob("*.py")))
    launchers = [path for path in browser_sources if launch_pattern.search(path.read_text("utf-8"))]
    assert launchers
    violations = []
    for path in launchers:
        source = path.read_text("utf-8")
        if (
            len(launch_pattern.findall(source)) != len(headless_true.findall(source))
            or headed_value.search(source)
            or "--headed" in source
        ):
            violations.append(path.relative_to(root).as_posix())
    assert violations == []


def test_verification_sops_never_start_or_open_the_product_browser() -> None:
    """F052 and SPEC D.2 120 require product-launching SOP commands to use --no-open."""

    root = Path(__file__).parents[1] / "verification"
    violations = []
    for path in sorted(root.rglob("SOP*.md")):
        in_code_block = False
        for line_number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            quoted_history = line.lstrip().startswith(">")
            negative_instruction = "Do not replace" in line or "was used only" in line
            command_text = in_code_block or "`nocturne" in line or "`.venv/bin/nocturne" in line
            if (
                command_text
                and not quoted_history
                and not negative_instruction
                and (
                    "nocturne open" in line
                    or ("nocturne up" in line and "--no-open" not in line)
                )
            ):
                violations.append(f"{path.relative_to(root)}:{line_number}")
    assert violations == []
