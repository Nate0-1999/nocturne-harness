from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic_ai import BinaryContent, RunContext, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from harness.browser_toolset import BrowserToolset
from harness.commands import browser_open_web_command
from harness.pydantic_ai_adapter import screenshot
from harness.tools_memory import MemoryToolContext
from harness.toolset import AgentLocation, ToolExecutionResult, ToolsetError


def _location(tmp_path: Path) -> AgentLocation:
    return AgentLocation(
        agent_id="agent",
        machine_id="machine",
        session_id="session",
        workspace_root=tmp_path,
        cwd=tmp_path / "project",
        fence_reads=False,
    )


def test_browser_fence_defaults_to_loopback_and_current_location(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    toolset = BrowserToolset(location=lambda: _location(tmp_path))

    toolset._require_allowed_url("http://localhost:8765/page", "thread")
    toolset._require_allowed_url("https://127.0.0.1:9443/page", "thread")
    toolset._require_allowed_url((project / "index.html").as_uri(), "thread")

    with pytest.raises(ToolsetError, match="outside the current agent location"):
        toolset._require_allowed_url((tmp_path / "elsewhere.html").as_uri(), "thread")
    with pytest.raises(ToolsetError, match="open web is walled"):
        toolset._require_allowed_url("https://example.com", "thread")


def test_open_web_consent_is_thread_scoped_and_restorable(tmp_path: Path) -> None:
    (tmp_path / "project").mkdir()
    restored: list[str] = []
    toolset = BrowserToolset(
        location=lambda: _location(tmp_path),
        consent_check=lambda thread_id: restored.append(thread_id) is None
        and thread_id == "restored",
    )

    toolset.grant_open_web("direct")
    toolset._require_allowed_url("https://example.com", "direct")
    toolset._require_allowed_url("https://example.com", "restored")
    toolset._require_allowed_url("https://example.com/again", "restored")

    with pytest.raises(ToolsetError, match="open web is walled"):
        toolset._require_allowed_url("https://example.com", "other")
    assert restored.count("restored") == 1


def test_browser_tool_surface_stays_small() -> None:
    assert all(
        BrowserToolset.owns(name)
        for name in ("navigate", "click", "type", "read_page", "screenshot")
    )
    assert not BrowserToolset.owns("bash")


@pytest.mark.asyncio
async def test_screenshot_becomes_native_model_image_content() -> None:
    class ScreenshotToolset:
        async def execute(self, tool_name: str, arguments: dict[str, object]):
            assert tool_name == "screenshot"
            assert arguments["_thread_id"] == "22222222-2222-4222-8222-222222222222"
            return ToolExecutionResult(
                "screenshot",
                "Screenshot of file:///page.html",
                True,
                image=b"\x89PNG\r\n\x1a\nimage",
                media_type="image/png",
            )

    context = MemoryToolContext(
        spine=object(),  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="machine",
        agent_id="agent",
        thread_id=UUID("22222222-2222-4222-8222-222222222222"),
        toolset=ScreenshotToolset(),  # type: ignore[arg-type]
    )
    result = await screenshot(
        RunContext(deps=context, model=TestModel(), usage=RunUsage())
    )

    assert isinstance(result, ToolReturn)
    assert isinstance(result.content, list)
    assert isinstance(result.content[-1], BinaryContent)
    assert result.content[-1].media_type == "image/png"


@pytest.mark.parametrize(
    ("text", "matches"),
    [
        ("/browser allow-web", True),
        ("  /browser allow-web  ", True),
        ("/browser allow-web please", False),
        ("allow web", False),
    ],
)
def test_browser_consent_command_is_exact(text: str, matches: bool) -> None:
    assert browser_open_web_command(text) is matches
