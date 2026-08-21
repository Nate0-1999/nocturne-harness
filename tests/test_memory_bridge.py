from __future__ import annotations

from uuid import UUID

import pytest

from harness.memory_bridge import MemorySharePolicy, SymphonyMemoryBridge
from harness.spine_client import JudgedContext, MemoryKind

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
MEMORY_ID = UUID("60000000-0000-4000-8000-000000000001")
BATCH_UID = UUID("70000000-0000-4000-8000-000000000001")
THREAD_ID = UUID("80000000-0000-4000-8000-000000000001")


class FakeSpine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def stage_symphony_memory(self, request):
        self.calls.append(("stage", request))
        return "staged"

    async def visible_symphony_memories(self, request):
        self.calls.append(("visible", request))
        return "visible"

    async def resolve_symphony_run(self, run_id, request):
        self.calls.append((run_id, request))
        return "resolved"


def test_leaf_context_share_is_strictly_smaller_than_conductor_share() -> None:
    """A-059 and P1.6 require leaf memory share below the conductor's share."""

    policy = MemorySharePolicy()

    assert policy.tokens(100_000, role="leaf") == 5_000
    assert policy.tokens(100_000, role="conductor") == 10_000
    assert policy.tokens(100_000, role="leaf") < policy.tokens(100_000, role="conductor")
    with pytest.raises(ValueError, match="leaf < conductor"):
        MemorySharePolicy(leaf=0.1, conductor=0.1)


@pytest.mark.asyncio
async def test_bridge_preserves_run_scoped_visibility_and_judged_winner_routing() -> None:
    """A-059 and P1.6 require own-run staging plus judged winner queue routing."""

    spine = FakeSpine()
    bridge = SymphonyMemoryBridge(  # type: ignore[arg-type]
        spine,
        principal_id="owner",
        machine_id="machine-local",
        thread_id=THREAD_ID,
    )
    origin = f"{RUN_ID}/root.2"

    await bridge.stage(
        memory_id=MEMORY_ID,
        run_id=RUN_ID,
        origin_agent=origin,
        label="Useful result",
        body="Only this attempt can see its staged result before judgment.",
        kind=MemoryKind.PROCEDURE,
        keywords=["symphony", "visibility"],
    )
    await bridge.visible(run_id=RUN_ID, origin_agent=origin)
    await bridge.resolve(
        run_id=RUN_ID,
        batch_uid=BATCH_UID,
        winner_origin_agent=origin,
        judged_context=JudgedContext(
            verdict="unanimous_pass",
            summary="Three independent judges selected attempt two.",
            judge_ids=["judge-a", "judge-b", "judge-c"],
            evidence_refs=["metrics://run/attempt-2"],
        ),
    )

    stage = spine.calls[0][1]
    visible = spine.calls[1][1]
    resolve = spine.calls[2][1]
    assert stage.run_id == RUN_ID and stage.origin_agent == origin
    assert stage.origin_thread_id == THREAD_ID
    assert visible.run_id == RUN_ID and visible.origin_agent == origin
    assert resolve.winner_origin_agent == origin
    assert resolve.judged_context.judge_ids == ["judge-a", "judge-b", "judge-c"]
