"""Real packaged-tool path comparison for M8MF; no tool or library mock."""

import asyncio
import json
import tempfile
from importlib.metadata import version
from pathlib import Path

from harness.pydantic_harness_adapter import adopted_skills
from harness.toolset import open_standard_toolset


async def main():
    rows = []
    with tempfile.TemporaryDirectory(prefix="m8mf-matrix-") as raw:
        root = Path(raw)
        for condition in ("missing", "file", "unreadable"):
            folder = root / condition
            if condition == "file":
                folder.write_text("not a folder")
            if condition == "unreadable":
                folder.mkdir()
                (folder / "note.txt").write_text("needle\n")
                folder.chmod(0)
            for name, args in (
                ("read", {"path": str(folder / "note.txt")}),
                ("write", {"path": str(folder / "note.txt"), "content": "needle\n"}),
                (
                    "edit",
                    {
                        "path": str(folder / "note.txt"),
                        "edits": [{"oldText": "needle", "newText": "changed"}],
                    },
                ),
                ("grep", {"path": str(folder), "pattern": "needle"}),
                ("find", {"path": str(folder), "pattern": "*.txt"}),
                ("ls", {"path": str(folder)}),
                ("bash", {"command": f"cd {folder} && printf M8MF-SHELL"}),
            ):
                toolset = await open_standard_toolset(cwd=root, workspace_root=root)
                try:
                    result = await toolset.execute(name, args)
                    row = {
                        "condition": condition,
                        "tool": name,
                        "success": result.success,
                        "content": result.content,
                        "boundary": result.boundary,
                    }
                except Exception as exc:
                    row = {
                        "condition": condition,
                        "tool": name,
                        "raised": type(exc).__name__,
                        "content": str(exc),
                    }
                finally:
                    await toolset.close()
                rows.append(row)
            try:
                skills = adopted_skills([folder])
                row = {
                    "condition": condition,
                    "tool": "skill catalog",
                    "count": len(skills),
                }
            except Exception as exc:
                row = {
                    "condition": condition,
                    "tool": "skill catalog",
                    "raised": type(exc).__name__,
                    "content": str(exc),
                }
            rows.append(row)
            if condition == "unreadable":
                folder.chmod(0o700)
    print(json.dumps({"version": version("nocturne-harness"), "rows": rows}, indent=2))


asyncio.run(main())
