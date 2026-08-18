"""Shared reachability wall and server-injected curtain for every fixture."""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from html import escape
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PRODUCT_PORT = 8765
_IDENTITY = re.compile(r"^[A-Z][A-Z0-9]* REGRESSION$")


class FixtureIsolationMiddleware:
    """Refuse the product port and inject a visible server-owned curtain."""

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
        if scope["type"] == "http":
            await self._serve_with_curtain(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _serve_with_curtain(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response_start: Message | None = None
        body_parts: list[bytes] = []
        inject = False

        async def send_with_curtain(message: Message) -> None:
            nonlocal inject, response_start
            if message["type"] == "http.response.start":
                response_start = message
                inject = _is_html(message) and _is_top_level_document(scope)
                if inject:
                    encoding = _header(message, b"content-encoding")
                    if encoding not in (None, b"identity"):
                        raise RuntimeError(
                            "fixture HTML must be uncompressed for curtain injection"
                        )
                    return
                await send(message)
                return

            if inject and message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                if response_start is None:
                    raise RuntimeError("fixture response body arrived before response start")
                body = _inject_curtain(b"".join(body_parts), self.fixture)
                await send(_curtain_headers(response_start, self.fixture, len(body)))
                await send({"type": "http.response.body", "body": body})
                return

            await send(message)

        await self.app(scope, receive, send_with_curtain)


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


def _is_html(message: Message) -> bool:
    content_type = _header(message, b"content-type")
    return content_type is not None and content_type.lower().startswith(b"text/html")


def _is_top_level_document(scope: Scope) -> bool:
    destination = next(
        (
            value.lower()
            for name, value in scope.get("headers", [])
            if name.lower() == b"sec-fetch-dest"
        ),
        None,
    )
    return destination != b"iframe"


def _header(message: Message, name: bytes) -> bytes | None:
    return next(
        (value for key, value in message.get("headers", []) if key.lower() == name),
        None,
    )


def _inject_curtain(body: bytes, fixture: str) -> bytes:
    packet_id = fixture.partition(" ")[0]
    safe_fixture = escape(fixture)
    safe_packet = escape(packet_id)
    curtain = (
        '<aside id="nocturne-fixture-curtain" role="banner" '
        f'data-fixture="{safe_fixture}" data-packet-id="{safe_packet}" '
        'style="position:fixed;inset:0 0 auto 0;z-index:2147483647;'
        'pointer-events:none;padding:10px 16px;border-bottom:4px solid #e6404d;'
        'background:#ffdc3d;color:#140900;font:800 14px/1.2 monospace;'
        'letter-spacing:.08em;text-align:center;box-sizing:border-box">'
        f'FIXTURE · {safe_fixture} · PACKET {safe_packet} · NOT THE OWNER APP'
        "</aside>"
    ).encode()
    lowered = body.lower()
    closing_body = lowered.rfind(b"</body>")
    if closing_body >= 0:
        return body[:closing_body] + curtain + body[closing_body:]
    return curtain + body


def _curtain_headers(message: Message, fixture: str, body_size: int) -> Message:
    packet_id = fixture.partition(" ")[0]
    headers = [
        (name, value)
        for name, value in message.get("headers", [])
        if name.lower()
        not in {b"content-length", b"x-nocturne-fixture", b"x-nocturne-fixture-packet"}
    ]
    headers.extend(
        (
            (b"content-length", str(body_size).encode("ascii")),
            (b"x-nocturne-fixture", fixture.encode("ascii")),
            (b"x-nocturne-fixture-packet", packet_id.encode("ascii")),
        )
    )
    return {**message, "headers": headers}


__all__ = ["PRODUCT_PORT", "install_fixture_isolation"]
