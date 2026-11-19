"""M8UP: real installed file/shell/background fences; no model or owner paths."""

import asyncio
import json
import shlex
import tempfile
from dataclasses import asdict
from pathlib import Path

from harness.toolset import open_standard_toolset


async def main():
    results = []
    for run in range(1, 4):
        with tempfile.TemporaryDirectory(prefix="m8up-fence-") as folder:
            base = Path(folder)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("untouched")
            (root / "escape").symlink_to(base, target_is_directory=True)
            tools = await open_standard_toolset(cwd=root, workspace_root=root, fence_reads=True)
            record = {"run": run}
            try:
                for name, args in (
                    ("read", {"path": str(outside)}),
                    ("write", {"path": str(outside), "content": "blocked"}),
                    ("write", {"path": "escape/outside.txt", "content": "blocked"}),
                    ("bash", {"command": f"printf blocked > {shlex.quote(str(outside))}"}),
                ):
                    reply = await tools.execute(name, args)
                    record.setdefault(name, []).append(asdict(reply))
                    assert outside.read_text() == "untouched"
                started = await tools.execute(
                    "start_shell",
                    {
                        "command": f"printf blocked > {shlex.quote(str(outside))}; "
                        "echo FENCE-CHECK; sleep 1"
                    },
                )
                assert started.success, started.content
                command_id = started.content.split("ID: ", 1)[1].split(".", 1)[0]
                await asyncio.sleep(0.5)
                read = await tools.execute("read_shell", {"command_id": command_id})
                record["background"] = asdict(read)
                assert outside.read_text() == "untouched"
                await tools.execute("stop_shell", {"command_id": command_id})
                record["outside_unchanged"] = True
                record["metadata_stayed_outside_project"] = not (
                    root / ".pydantic-ai-harness"
                ).exists()
                assert record["metadata_stayed_outside_project"]
            finally:
                await tools.close()
            results.append(record)
    print(json.dumps(results, indent=2, default=str))


asyncio.run(main())
