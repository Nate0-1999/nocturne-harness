"""Symphony startup context and the human's live memory selections. [P1.2, P2.2]"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from harness.context_window import ContextWindowTracker
from harness.progressive_prompt import render_workspace_context, workspace_location_path
from harness.spine_client import (
    FeedbackRequest,
    FeedbackSignal,
    InjectCommitRequest,
    InjectPrepareRequest,
)

# SPEC §2 component pointers: these describe the product, not the worker's target repository.
COMPONENT_REGISTRY = """<component_registry source="SPEC §2">
P1 — memory must outlive processes: Palace API and database, journal, memory bridge.
P2 — humans must see and steer: Rack, context bars, memory graph, recipe and agent views.
P3 — agents work where files are: workspace tools, supervisor, conductor, independent judges.
P4 — the product carries itself: daemon and CLI, toolset, verification suites, CI, releases.
</component_registry>"""


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


async def select_memory(output: Path, spine, memory_id, *, added: bool):
    """Keep feedback authoritative; selections apply at the next provider request. [C.6]"""
    observation = json.loads((output / "visualization.json").read_text())
    if observation["state"] != "running" or (output / "result.json").exists():
        raise ValueError("This worker has finished. Its context is available for inspection.")
    current = json.loads((output / "context.json").read_text())
    injection = current["injection"]
    if injection is None:
        raise ValueError("Independent judges do not receive ambient memories.")
    cards = injection["injected"] + injection["near_misses"] + current["removed"]
    if str(memory_id) not in {card["memory_id"] for card in cards}:
        raise ValueError("This memory is not in the worker's injection or suggestions.")
    await spine.submit_feedback(
        FeedbackRequest(
            injection_id=current["sources"][str(memory_id)],
            memory_id=memory_id,
            signal=FeedbackSignal.MID_THREAD_ADDED if added else FeedbackSignal.MID_THREAD_REMOVED,
        )
    )
    path = output / "memory-selection.json"
    selected = json.loads(path.read_text()) if path.exists() else {"added": [], "removed": []}
    for field in ("added", "removed"):
        selected[field] = [value for value in selected[field] if value != str(memory_id)]
    selected["added" if added else "removed"].append(str(memory_id))
    write_json(path, selected)
    return {"accepted": True, "applies": "next model request"}


class WorkerContext:
    def __init__(self, *, assignment, output, context, resolution):
        self.assignment = assignment
        self.output = output
        self.context = context
        self.resolution = resolution
        self.prepared = None
        self.tracker = ContextWindowTracker()
        self.last_selection = None
        self.workspace = ""
        self.cards = {}
        self.sources = {}

    async def render(self, captured) -> str:
        location = self.context.toolset.location()
        self.workspace = render_workspace_context(location) + "\n\n" + COMPONENT_REGISTRY
        selection_path = self.output / "memory-selection.json"
        selection = json.loads(selection_path.read_text()) if selection_path.exists() else {}
        key = (str(location.cwd), selection)
        if self.assignment["stage"] != "judge" and key != self.last_selection:
            current = (
                set()
                if self.prepared is None
                else {str(card.memory_id) for card in self.prepared.injected}
            )
            current.update(selection.get("added", []))
            current.difference_update(selection.get("removed", []))
            self.prepared = await self.context.spine.prepare_injection(
                InjectPrepareRequest(
                    thread_id=uuid5(NAMESPACE_URL, str(self.output)),
                    agent_id=self.context.agent_id,
                    machine_id=self.context.machine_id,
                    principal_id=self.context.principal_id,
                    project_key=self.context.project_key,
                    location_path=workspace_location_path(location),
                    current_location=str(location.cwd),
                    prompt=self.assignment["brief"],
                    model_context_tokens=self.resolution.context_tokens,
                    mode="gate" if self.prepared is None else "autonomous",
                    current_memory_ids=sorted(current),
                    confirmed_memory_ids=selection.get("added", []),
                    excluded_memory_ids=selection.get("removed", []),
                )
            )
            if self.prepared.final_block is None:
                committed = await self.context.spine.commit_injection(
                    InjectCommitRequest(
                        injection_id=self.prepared.injection_id,
                        removed=[],
                        added_back=[],
                    )
                )
                self.prepared = self.prepared.model_copy(
                    update={"final_block": committed.final_block},
                )
            self.last_selection = key
            for card in (*self.prepared.injected, *self.prepared.near_misses):
                self.cards[str(card.memory_id)] = card.model_dump(mode="json")
                self.sources[str(card.memory_id)] = str(self.prepared.injection_id)
        self.publish(captured)
        followups = Path(self.assignment["followups"])
        clarification = (
            json.loads(followups.read_text()).get(self.assignment["attempt_id"], [])
            if followups.exists()
            else []
        )
        return "\n\n".join(
            (
                self.workspace,
                self.prepared.final_block or "" if self.prepared is not None else "",
                "Conductor clarifications:\n" + json.dumps(clarification),
            )
        )

    def publish(self, captured):
        prepared = self.prepared
        self.tracker.record(
            thread_id=self.context.agent_id,
            captured=captured,
            resolution=self.resolution,
            memory_block=None if prepared is None else prepared.final_block,
            memory_allocation=None if prepared is None else prepared.memory_allocation,
            workspace_block=self.workspace,
        )
        write_json(
            self.output / "context.json",
            {
                "worker_id": self.assignment["prompt_id"],
                "agent_id": self.context.agent_id,
                "stage": self.assignment["stage"],
                "attempt_id": self.assignment["attempt_id"],
                "observation": self.tracker.snapshot(self.context.agent_id).model_dump(mode="json"),
                "injection": None if prepared is None else prepared.model_dump(mode="json"),
                "sources": self.sources,
                "removed": [
                    self.cards[value]
                    for value in (
                        self.last_selection[1].get("removed", []) if self.last_selection else []
                    )
                    if value in self.cards
                ],
            },
        )
