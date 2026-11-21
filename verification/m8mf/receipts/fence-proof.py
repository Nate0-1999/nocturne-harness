"""Installed-wheel fence neighbors for F246, using only disposable files."""

import asyncio
import json
import tempfile
from pathlib import Path

from harness.toolset import open_standard_toolset


async def main():
    results = []
    for run in (3, 4, 5):
        with tempfile.TemporaryDirectory(prefix="m8mf-fence-") as directory:
            base = Path(directory)
            root = base / "project"
            root.mkdir()
            outside = base / "sentinel.txt"
            outside.write_text("OUTSIDE UNCHANGED\n")
            (root / "link.txt").symlink_to(outside)
            toolset = await open_standard_toolset(cwd=root, workspace_root=root, fence_reads=True)
            calls = []
            try:
                for name, args in [
                    ("read", {"path": str(outside)}),
                    ("write", {"path": str(outside), "content": "CHANGED"}),
                    ("write", {"path": "link.txt", "content": "CHANGED"}),
                    ("bash", {"command": f"printf CHANGED > {outside}"}),
                ]:
                    result = await toolset.execute(name, args)
                    calls.append(
                        {
                            "tool": name,
                            "success": result.success,
                            "boundary": result.boundary,
                            "content": result.content,
                        }
                    )
                assert outside.read_text() == "OUTSIDE UNCHANGED\n"
                assert all(not call["success"] and call["boundary"] for call in calls[:3])
            finally:
                await toolset.close()
            results.append({"run": run, "sentinel_unchanged": True, "calls": calls})
    print(json.dumps(results, indent=2))


asyncio.run(main())
