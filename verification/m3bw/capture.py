"""Reproduce M3BW's headless verification-identity screenshot."""

from __future__ import annotations

import asyncio
from pathlib import Path

from harness.toolset_runtime import LazyStandardToolset

THREAD_ID = "44444444-4444-4444-8444-444444444444"


async def main() -> None:
    root = Path(__file__).resolve().parents[2]
    toolset = LazyStandardToolset(
        cwd=root,
        workspace_root=root.parent,
        agent_id="m3bw-verification",
        machine_id="headless-proof",
    )

    def arguments(**values: object) -> dict[str, object]:
        return {"_thread_id": THREAD_ID, **values}

    try:
        page = (Path(__file__).with_name("tiny-page.html")).as_uri()
        await toolset.execute("navigate", arguments(url=page))
        await toolset.execute(
            "type",
            arguments(selector="#owner-note", text="real owner proof"),
        )
        await toolset.execute("click", arguments(selector="#reveal"))
        read = await toolset.execute("read_page", arguments())
        if "Amber constellation — real owner proof" not in read.content:
            raise RuntimeError("browser interaction did not reach the expected visible state")
        screenshot = await toolset.execute("screenshot", arguments())
        if screenshot.image is None or screenshot.media_type != "image/png":
            raise RuntimeError("browser screenshot did not return a PNG")
        Path(__file__).with_name("browser-hands.png").write_bytes(screenshot.image)
    finally:
        await toolset.close()


if __name__ == "__main__":
    asyncio.run(main())
