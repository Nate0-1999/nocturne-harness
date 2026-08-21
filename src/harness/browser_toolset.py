"""Headless Playwright adapter behind the Harness-owned toolset seam."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    async_playwright,
)

from harness.toolset import AgentLocation, ToolExecutionResult, ToolName, ToolsetError

_BROWSER_TOOLS = frozenset({"navigate", "click", "type", "read_page", "screenshot"})
_MAX_PAGE_TEXT = 20_000


@dataclass(slots=True)
class _ThreadBrowser:
    context: BrowserContext
    page: Page


class BrowserToolset:
    """Own one headless browser with an isolated context for each owner thread."""

    def __init__(
        self,
        *,
        location: Callable[[], AgentLocation],
        consent_check: Callable[[str], bool] | None = None,
    ) -> None:
        self._location = location
        self._consent_check = consent_check or (lambda _thread_id: False)
        self._grants: set[str] = set()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._threads: dict[str, _ThreadBrowser] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def owns(tool_name: ToolName) -> bool:
        return tool_name in _BROWSER_TOOLS

    def grant_open_web(self, thread_id: str) -> None:
        if not thread_id:
            raise ValueError("browser consent requires a thread id")
        self._grants.add(thread_id)

    def set_consent_check(self, consent_check: Callable[[str], bool]) -> None:
        self._consent_check = consent_check

    def open_web_allowed(self, thread_id: str) -> bool:
        if thread_id in self._grants:
            return True
        allowed = self._consent_check(thread_id)
        if allowed:
            self._grants.add(thread_id)
        return allowed

    async def execute(
        self,
        tool_name: ToolName,
        arguments: Mapping[str, object],
    ) -> ToolExecutionResult:
        if not self.owns(tool_name):
            raise ValueError(f"unsupported browser tool: {tool_name}")
        thread_id = _required_string(arguments, "_thread_id")
        if tool_name == "navigate":
            self._require_allowed_url(_required_string(arguments, "url"), thread_id)
        owned = await self._thread(thread_id)
        if tool_name != "navigate":
            self._require_allowed_url(owned.page.url, thread_id)
        try:
            if tool_name == "navigate":
                url = _required_string(arguments, "url")
                response = await owned.page.goto(url, wait_until="domcontentloaded")
                status = None if response is None else response.status
                suffix = "" if status is None else f" ({status})"
                return ToolExecutionResult(tool_name, f"Opened {owned.page.url}{suffix}", True)
            if tool_name == "click":
                selector = _required_string(arguments, "selector")
                await owned.page.locator(selector).click()
                return ToolExecutionResult(tool_name, f"Clicked {selector}", True)
            if tool_name == "type":
                selector = _required_string(arguments, "selector")
                value = _required_string(arguments, "text", allow_blank=True)
                await owned.page.locator(selector).fill(value)
                return ToolExecutionResult(tool_name, f"Typed into {selector}", True)
            if tool_name == "read_page":
                title = await owned.page.title()
                body = await owned.page.locator("body").inner_text()
                clipped = body[:_MAX_PAGE_TEXT]
                suffix = "\n[page text clipped]" if len(body) > len(clipped) else ""
                return ToolExecutionResult(
                    tool_name,
                    f"URL: {owned.page.url}\nTitle: {title}\n\n{clipped}{suffix}",
                    True,
                )
            image = await owned.page.screenshot(type="png")
            return ToolExecutionResult(
                tool_name,
                f"Screenshot of {owned.page.url}",
                True,
                image=image,
                media_type="image/png",
            )
        except ToolsetError:
            raise
        except Exception as exc:
            return ToolExecutionResult(
                tool_name,
                str(exc).strip() or type(exc).__name__,
                False,
            )

    async def close(self) -> None:
        self._threads.clear()
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _thread(self, thread_id: str) -> _ThreadBrowser:
        existing = self._threads.get(thread_id)
        if existing is not None:
            return existing
        async with self._lock:
            existing = self._threads.get(thread_id)
            if existing is not None:
                return existing
            browser = await self._owned_browser()
            context = await browser.new_context()
            context.set_default_timeout(10_000)

            async def fence(route: Route) -> None:
                try:
                    self._require_allowed_url(route.request.url, thread_id)
                except ToolsetError:
                    await route.abort("blockedbyclient")
                else:
                    await route.continue_()

            await context.route("**/*", fence)
            page = await context.new_page()
            owned = _ThreadBrowser(context=context, page=page)
            self._threads[thread_id] = owned
            return owned

    async def _owned_browser(self) -> Browser:
        if self._browser is not None:
            return self._browser
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as exc:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            raise ToolsetError(
                "the headless Chromium runtime is unavailable; run `nocturne init` and retry"
            ) from exc
        return self._browser

    def _require_allowed_url(self, url: str, thread_id: str) -> None:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme in {"about", "data", "blob"}:
            return
        if scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            cwd = self._location().cwd.resolve()
            if parsed.netloc not in {"", "localhost"} or not path.is_relative_to(cwd):
                raise ToolsetError(f"file URL is outside the current agent location: {url}")
            return
        if scheme in {"http", "https"}:
            if _is_loopback(parsed.hostname):
                return
            if self.open_web_allowed(thread_id):
                return
            raise ToolsetError(
                "open web is walled for this thread; the owner can type "
                "`/browser allow-web` once, then retry"
            )
        raise ToolsetError(f"browser URL scheme is not allowed: {scheme or '(missing)'}")


def _required_string(
    arguments: Mapping[str, object], key: str, *, allow_blank: bool = False
) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError(f"{key} must be a {'string' if allow_blank else 'nonblank string'}")
    return value


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
