"""Local-only owner surface with one judged Symphony winner batch."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import MemoryStatus, QueueCard
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import UPDATED, _memory, _model
from verification.m2ux1.scenario_app import LayoutSpine

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
BATCH_UID = UUID("70000000-0000-4000-8000-000000000006")


class SymphonyQueueSpine(LayoutSpine):
    def __init__(self) -> None:
        super().__init__()
        item_uid = "01ARZ3NDEKTSV4RRFFQ69G5FA6"
        self.cards[item_uid] = QueueCard(
            item_uid=item_uid,
            candidate=_memory(
                UUID("60000000-0000-4000-8000-000000000006"),
                "Preserve attempt-scoped findings",
                "A worker sees committed Palace memory plus only its own staged results.",
                status=MemoryStatus.CANDIDATE,
                keywords=["symphony", "visibility", "lineage"],
            ),
            birthplace="symphony",
            birthplace_thread_id=None,
            batch_uid=BATCH_UID,
            source_name=None,
            source_sha256=None,
            birthplace_run_id=RUN_ID,
            birthplace_origin_agent=f"{RUN_ID}/root.2",
            judged_context={
                "verdict": "unanimous_pass",
                "summary": "Attempt two preserved the visibility boundary.",
                "judge_ids": ["motivation", "implementation", "performance"],
                "evidence_refs": ["verification/sym6/two-attempt-run"],
            },
            verdict="new",
            neighbors=[],
            target_ids=[],
            state="pending",
            created_at=UPDATED,
        )


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="sym6-verification",
        machine_id="sym6-verification",
        agent_id="sym6-verification",
        chat_model="local:sym6-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=SymphonyQueueSpine(),  # type: ignore[arg-type]
    )
    app = FastAPI(title="SYM6 deterministic Palace Queue verification")
    install_fixture_isolation(app, "SYM6 REGRESSION")
    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
