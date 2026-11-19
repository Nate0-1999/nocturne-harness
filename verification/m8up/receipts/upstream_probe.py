"""SD-047: observe today's candidate features without adopting them."""

import asyncio
import json
import tempfile
from pathlib import Path

from pydantic_ai import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace
from pydantic_ai_harness import Skills
from pydantic_ai_harness.file_system import FileSystemToolset


async def main():
    with tempfile.TemporaryDirectory(prefix="m8up-upstream-") as folder:
        root = Path(folder)
        (root / "note.txt").write_text("one\nmatch\nthree\n")
        skill = root / "skills" / "review"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: review\ndescription: Review the change.\n---\nRead references/marker.txt.\n"
        )
        (skill / "references" / "marker.txt").write_text("M8UP-RESOURCE-OK")
        backend = LocalWorkspaceBackend(root)
        fs = FileSystemToolset(
            allowed_patterns=[],
            denied_patterns=[],
            read_only_patterns=[],
            max_read_lines=2000,
            max_list_results=1000,
            max_search_results=1000,
            max_find_results=1000,
        )
        context_lines = await fs.grep("match", context=1, workspace=backend)
        assert "one" in context_lines and "three" in context_lines
        ctx = RunContext(
            deps=None,
            model=None,
            usage=RunUsage(),
            workspace=Workspace(backend),
            loaded_capability_ids={"review"},
        )
        capability = await Skills(root / "skills", read_files=True).for_run(ctx)
        leaves = []
        capability.apply(leaves.append)
        resource = None
        for leaf in leaves:
            toolset = leaf.get_toolset()
            if toolset:
                tools = await toolset.get_tools(ctx)
                if "read_skill_file" in tools:
                    resource = await toolset.call_tool(
                        "read_skill_file",
                        {"skill": "review", "path": "references/marker.txt"},
                        ctx,
                        tools["read_skill_file"],
                    )
        assert resource == "M8UP-RESOURCE-OK"
        print(
            json.dumps(
                {
                    "grep_context": context_lines,
                    "bundled_resource": resource,
                    "adopted_in_product": False,
                },
                indent=2,
            )
        )


asyncio.run(main())
