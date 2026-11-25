import asyncio

import pytest

from harness.t3_passthrough import T3PassThrough, hosting_answer, shown_thread

PAGE = "http://127.0.0.1:8765"


def test_only_nocturnes_own_page_is_named_in_place_of_t3s_refusal():
    """A-101 / SD-114: the one changed answer admits this home's page and no other."""
    answer = hosting_answer(
        [
            (b"Content-Type", b"text/html"),
            (b"content-security-policy", b"default-src 'self'; Frame-Ancestors 'none'"),
            (b"Content-Security-Policy", b"frame-ancestors *"),
            (b"X-Frame-Options", b"DENY"),
        ],
        PAGE,
    )
    assert answer == [
        (b"Content-Type", b"text/html"),
        (b"content-security-policy", b"default-src 'self'"),
        (b"Content-Security-Policy", b"frame-ancestors " + PAGE.encode()),
    ]


async def _ask(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    answer = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    return answer


@pytest.mark.asyncio
async def test_pass_through_is_loopback_only_and_reads_every_request_before_t3_does(tmp_path):
    """A-101 / SD-114: no other host name and no request riding a checked one reaches T3."""
    seen, finished = [], asyncio.Event()

    async def t3(reader, writer):
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Security-Policy: frame-ancestors 'none'\r\n"
            b"X-Frame-Options: DENY\r\nContent-Length: 2\r\n\r\nok"
        )
        await writer.drain()
        writer.write_eof()
        seen.append(await reader.read())
        writer.close()
        finished.set()

    upstream = await asyncio.start_server(t3, "127.0.0.1", 0)
    through = T3PassThrough()
    try:
        await through.start(upstream.sockets[0].getsockname()[1], PAGE, tmp_path / "port")
        assert through._server.sockets[0].getsockname()[0] == "127.0.0.1"
        host = f"Host: 127.0.0.1:{through.port}\r\n".encode()

        renamed = await _ask(through.port, b"GET / HTTP/1.1\r\nHost: rebound.example\r\n\r\n")
        chunked = await _ask(
            through.port, b"POST / HTTP/1.1\r\n" + host + b"Transfer-Encoding: chunked\r\n\r\n"
        )
        assert renamed.startswith(b"HTTP/1.1 421") and chunked.startswith(b"HTTP/1.1 411")
        assert seen == []

        smuggled = b"GET /second HTTP/1.1\r\nHost: rebound.example\r\n\r\n"
        answer = await _ask(through.port, b"GET /first HTTP/1.1\r\n" + host + b"\r\n" + smuggled)
        assert answer.endswith(b"\r\n\r\nok")
        assert b"frame-ancestors " + PAGE.encode() in answer
        assert b"'none'" not in answer and b"X-Frame-Options" not in answer
        await asyncio.wait_for(finished.wait(), 5)
        assert seen[0].startswith(b"GET /first ") and seen[1] == b""
    finally:
        await through.close()
        upstream.close()
        await upstream.wait_closed()


def test_only_this_t3s_own_thread_address_names_the_open_thread():
    """A-104 / SD-124: any other address says nothing, so a silent T3 breaks nothing."""
    origin = "http://127.0.0.1:9"

    def read(*addresses, environment="env-1"):
        return shown_thread([(b"Referer", value) for value in addresses], origin, environment)

    assert read(b"http://127.0.0.1:9/env-1/thread-7") == "thread-7"
    for address in (
        b"http://127.0.0.1:9/",  # the origin alone
        b"http://127.0.0.1:9",
        b"http://127.0.0.1:9/env-2/thread-7",  # another T3's environment
        b"http://127.0.0.1:99/env-1/thread-7",  # another port or name
        b"http://localhost:9/env-1/thread-7",
        b"http://127.0.0.1:9/draft/thread-7",
        b"http://127.0.0.1:9/env-1/",
        b"http://127.0.0.1:9/env-1/thread-7/",
        b"http://127.0.0.1:9/env-1/thread-7/files",
        b"http://127.0.0.1:9/env-1/thread-7?token=secret",
        b"http://127.0.0.1:9/env-1/..%2fthread",
        b"\xff\xfe",
    ):
        assert read(address) is None, address
    assert read() is None
    assert read(b"http://127.0.0.1:9//thread-7", environment="") is None


@pytest.mark.asyncio
async def test_a_request_that_names_no_thread_passes_and_leaves_the_open_thread(tmp_path):
    """A-104 / A-101: the address is read, never changed; without it the Stage stays where it is."""
    seen = []

    async def t3(reader, writer):
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(t3, "127.0.0.1", 0)
    through = T3PassThrough()
    try:
        port = upstream.sockets[0].getsockname()[1]
        await through.start(port, PAGE, tmp_path / "port", "env-1")
        host = f"Host: 127.0.0.1:{through.port}\r\n".encode()
        here = f"Referer: {through.origin}/env-1/thread-7\r\n".encode()
        assert through.thread is None
        for referer, thread in (
            (b"", None),
            (here, "thread-7"),
            (b"", "thread-7"),
            (f"Referer: {through.origin}/env-2/thread-8\r\n".encode(), "thread-7"),
            (b"Referer: \xff/env-1/x y\r\n", "thread-7"),
        ):
            answer = await _ask(through.port, b"GET /api HTTP/1.1\r\n" + host + referer + b"\r\n")
            assert answer.endswith(b"\r\n\r\nok") and through.thread == thread
        assert here in seen[1] and len(seen) == 5
    finally:
        await through.close()
        upstream.close()
        await upstream.wait_closed()
    assert through.thread is None
