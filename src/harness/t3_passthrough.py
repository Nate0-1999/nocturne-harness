"""This machine's pass-through to the front T3 server (A-101, SD-114).

T3 answers every page that tries to show it in a frame with "nobody may host this page".
Requests pass through here unchanged; the one answer becomes "only Nocturne's own page".
"""

import asyncio
import contextlib
import re
from pathlib import Path
from urllib.parse import unquote

_LIMIT = 64 * 1024
_THREAD = re.compile(
    r"(?:[0-9A-Za-z-]{1,64}|thread:provider:[A-Za-z0-9_-]+:provider-instance:nocturne:native-thread:[a-f0-9-]{36})"
)


def hosting_answer(headers: list[tuple[bytes, bytes]], page: str) -> list[tuple[bytes, bytes]]:
    """Replace T3's "nobody may host this page" with "only this Nocturne page may"."""
    # M8TT: T3's page also names T3 Connect and Axiom; it may connect to this address alone.
    ours = b"frame-ancestors " + page.encode("ascii") + b"; connect-src 'self'"
    answer = []
    for name, value in headers:
        lower = name.lower()
        if lower == b"x-frame-options":
            continue  # This older header cannot name one page; the last line below does.
        if lower == b"content-security-policy":
            rules = [rule.strip() for rule in value.split(b";")]
            value = b"; ".join(
                rule for rule in rules if rule and rule.split()[0].lower() != b"frame-ancestors"
            )
            if not value:
                continue
        answer.append((name, value))
    answer.append((b"Content-Security-Policy", ours))
    return answer


def shown_thread(headers: list[tuple[bytes, bytes]], origin: str, environment: str) -> str | None:
    """The thread T3's page is on, by its own address on a request it sends (SD-124).

    T3 does not promise this: its page happens to send requests after it moves, and the browser
    names the page's address on them. Only the thread id is read, and only from an address that
    is exactly <this pass-through>/<this T3's environment>/<thread>; anything else says nothing.
    """
    prefix = f"{origin}/{environment}/".encode()
    for value in _values(headers, b"referer"):
        if environment and value.startswith(prefix):
            thread = unquote(value[len(prefix) :].decode("ascii", errors="replace"))
            if _THREAD.fullmatch(thread):
                return thread
    return None


def _parse(head: bytes) -> tuple[bytes, list[tuple[bytes, bytes]]]:
    first, *lines = head[:-4].split(b"\r\n")
    headers = []
    for line in lines:
        name, separator, value = line.partition(b":")
        if not separator or name != name.strip() or not name:
            raise ValueError("header")
        headers.append((name, value.strip()))
    return first, headers


def _values(headers, wanted: bytes) -> list[bytes]:
    return [value for name, value in headers if name.lower() == wanted]


def _join(first: bytes, headers) -> bytes:
    return b"\r\n".join([first, *(name + b": " + value for name, value in headers)]) + b"\r\n\r\n"


async def _pipe(reader, writer):
    with contextlib.suppress(OSError, asyncio.IncompleteReadError):
        while chunk := await reader.read(_LIMIT):
            writer.write(chunk)
            await writer.drain()
    with contextlib.suppress(OSError):
        writer.close()


class T3PassThrough:
    """One browser request per connection, so every request's Host is read before T3 sees it."""

    def __init__(self):
        self.port = 0
        self.upstream = 0
        self.page = ""
        self.environment = ""
        self.thread = None
        self._server = None
        self._tasks = set()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(
        self, upstream: int, page: str, remembered: Path, environment: str = ""
    ) -> None:
        self.upstream, self.page, self.environment = upstream, page, environment
        if self._server is not None:
            return
        # T3's page keeps its own setup by address, so a restart asks for the same port again.
        try:
            port = int(remembered.read_text())
            self._server = await self._listen(port)
        except (OSError, ValueError, OverflowError):
            self._server = await self._listen(0)
        self.port = self._server.sockets[0].getsockname()[1]
        remembered.write_text(str(self.port))

    def _listen(self, port: int):
        return asyncio.start_server(self._accept, "127.0.0.1", port, limit=_LIMIT)

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._server.wait_closed()
        self._server = None
        self.port = 0
        self.thread = None

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            await self._relay(reader, writer)
        except (OSError, ValueError, EOFError, asyncio.LimitOverrunError):
            pass  # A broken or stopped side ends this one request; T3's page reconnects itself.
        finally:
            self._tasks.discard(task)
            with contextlib.suppress(OSError):
                writer.close()

    async def _refuse(self, writer, status: bytes):
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()

    async def _relay(self, reader, writer):
        async with asyncio.timeout(30):
            first, headers = _parse(await reader.readuntil(b"\r\n\r\n"))
        if _values(headers, b"host") != [f"127.0.0.1:{self.port}".encode()]:
            # Another name for this address (a rebound domain) is not this machine's own page.
            await self._refuse(writer, b"421 Misdirected Request")
            return
        self.thread = shown_thread(headers, self.origin, self.environment) or self.thread
        if _values(headers, b"transfer-encoding"):
            await self._refuse(writer, b"411 Length Required")
            return
        lengths = _values(headers, b"content-length")
        if len(lengths) > 1 or (lengths and not lengths[0].isdigit()):
            await self._refuse(writer, b"400 Bad Request")
            return
        socket = any(b"upgrade" in value.lower() for value in _values(headers, b"connection"))
        if not socket:
            headers = [(n, v) for n, v in headers if n.lower() != b"connection"]
            headers.append((b"Connection", b"close"))
        up_reader, up_writer = await asyncio.open_connection(
            "127.0.0.1", self.upstream, limit=_LIMIT
        )
        try:
            up_writer.write(_join(first, headers))
            if lengths:
                remaining = int(lengths[0])
                while remaining:
                    chunk = await reader.read(min(remaining, _LIMIT))
                    if not chunk:
                        raise asyncio.IncompleteReadError(b"", remaining)
                    up_writer.write(chunk)
                    await up_writer.drain()
                    remaining -= len(chunk)
            await up_writer.drain()
            status, answer = _parse(await up_reader.readuntil(b"\r\n\r\n"))
            answer = hosting_answer(answer, self.page)
            upgraded = status.split()[1:2] == [b"101"]
            if not upgraded:
                answer = [(n, v) for n, v in answer if n.lower() != b"connection"]
                answer.append((b"Connection", b"close"))
            writer.write(_join(status, answer))
            await writer.drain()
            if upgraded:
                back = asyncio.create_task(_pipe(reader, up_writer))
                try:
                    await _pipe(up_reader, writer)
                finally:
                    back.cancel()
                    await asyncio.gather(back, return_exceptions=True)
            else:
                await _pipe(up_reader, writer)
        finally:
            with contextlib.suppress(OSError):
                up_writer.close()
