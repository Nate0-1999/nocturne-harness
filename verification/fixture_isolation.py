"""Shared reachability wall for every deterministic Harness fixture. [A-038]"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

PRODUCT_PORT = 8765
_IDENTITY = re.compile(r"^[A-Z][A-Z0-9]* REGRESSION$")


class FixtureIsolationMiddleware:
    """Refuse the product port and force a visible server-verified marker."""

    def __init__(self, app: ASGIApp, *, fixture: str) -> None:
        self.app = app
        self.fixture = fixture

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        port = _request_port(scope)
        if port == PRODUCT_PORT:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008, "reason": "fixture port"})
                return
            if scope["type"] == "http":
                response = PlainTextResponse(
                    "FIXTURE REFUSED: port 8765 belongs to the owner app.",
                    status_code=409,
                )
                await response(scope, receive, send)
                return
        if scope["type"] == "http" and scope.get("path") == "/":
            query = _query(scope)
            if query.get("fixture") != [self.fixture]:
                query["fixture"] = [self.fixture]
                flattened = [(key, item) for key, values in query.items() for item in values]
                response = RedirectResponse(f"/?{urlencode(flattened)}", status_code=307)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def install_fixture_isolation(app: FastAPI, fixture: str) -> None:
    """Install the shared wall before a scenario mounts the production app."""

    if not _IDENTITY.fullmatch(fixture):
        raise ValueError("fixture identity must be '<PACKET> REGRESSION'")
    app.add_middleware(FixtureIsolationMiddleware, fixture=fixture)

    @app.get("/__scenario__/identity")
    async def fixture_identity() -> dict[str, object]:
        return {"fixture": fixture, "deterministic": True}


def _query(scope: Scope) -> MutableMapping[str, list[str]]:
    from urllib.parse import parse_qs

    raw = scope.get("query_string", b"")
    return parse_qs(raw.decode("ascii"), keep_blank_values=True)


def _request_port(scope: Scope) -> int | None:
    server = scope.get("server")
    if isinstance(server, tuple) and len(server) == 2 and isinstance(server[1], int):
        return server[1]
    for name, value in scope.get("headers", []):
        if name.lower() == b"host":
            host = value.decode("ascii", errors="ignore")
            _, separator, raw_port = host.rpartition(":")
            if separator and raw_port.isdigit():
                return int(raw_port)
    return None


__all__ = ["PRODUCT_PORT", "install_fixture_isolation"]
