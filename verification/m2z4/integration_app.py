"""Disposable M2Z4 proof joining the real learner worker to the real Console.

This module is verification-only.  Its single scenario route inserts fixture-
graded events into a fresh pgvector Testcontainer and wakes Spine's actual
``LearnerWorker``.  It never points at, copies, or mutates an owner Palace.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException
from spine.config import Settings as SpineSettings
from spine.db.migrate import packaged_head, upgrade_head
from spine.db.models import InjectionEvent, LearnerRun, ScorerActivation, ScorerConfig
from spine.db.session import make_session_factory
from spine.learner.contracts import RetrainResponse as SpineRetrainResponse
from spine.main import create_app as create_spine_app
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from harness.daemon import create_app
from harness.spine_client import (
    RackScorerActivateRequest,
    RackScorerAuditionRequest,
    RackScorerSimulationRequest,
    ScorerAuditionRequest,
    ScorerAuditionResponse,
    ScorerConfigurationView,
    ScorerConsoleQuery,
    ScorerConsoleSnapshot,
    ScorerSimulationRequest,
    ScorerSimulationResponse,
    SpineClient,
    SpineClientError,
)
from verification.fixture_isolation import install_fixture_isolation

FIXTURE = "M2Z4 REGRESSION"
TOKEN = "m2z4-disposable-token"
PRINCIPAL_ID = "m2z4-disposable-owner"
MACHINE_ID = "disposable-owner-machine"
THREAD_ID = UUID("00000000-0000-4000-8000-000000000404")
CURRENT_INJECTION_ID = UUID("00000000-0000-4000-8000-000000001003")
INCUMBENT_VERSION = "v0"


class _UnusedEmbeddingProvider:
    """Keep this scorer-only proof incapable of making an embedding call."""

    model = "m2z4-unused-embedding-1536"
    dimensions = 1536

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        del texts
        raise AssertionError("the M2Z4 scorer proof must not request embeddings")


def _asyncpg_url(url: str) -> str:
    scheme, separator, rest = url.partition("://")
    if not separator or not scheme.startswith("postgres"):
        raise RuntimeError("Testcontainers returned a malformed PostgreSQL URL")
    return f"postgresql+asyncpg://{rest}"


def _postgres_container_type() -> type[Any]:
    """Load Spine's verification dependency without expanding Harness runtime deps."""

    try:
        from testcontainers.postgres import PostgresContainer
    except ModuleNotFoundError as first_error:
        checkout = Path(__file__).resolve().parents[3]
        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        spine_site = checkout / "spine" / ".venv" / "lib" / version / "site-packages"
        if not spine_site.is_dir():
            raise RuntimeError(
                "M2Z4 integration proof needs the sibling Spine .venv; run `uv sync --locked` "
                "in ../spine first"
            ) from first_error
        sys.path.append(str(spine_site))
        try:
            from testcontainers.postgres import PostgresContainer
        except ModuleNotFoundError as second_error:
            raise RuntimeError(
                "the sibling Spine .venv does not contain its Testcontainers test dependency"
            ) from second_error
    return PostgresContainer


def _event(
    *,
    event_uid: str,
    injection_id: UUID,
    memory_id: UUID,
    label: str,
    body: str,
    features: tuple[float, float, float, float, float, float],
    score: float,
    rank: int,
    shown_as: str,
    outcome: str | None,
    ts: datetime,
) -> InjectionEvent:
    sem, kw, time, proj, freq, hist = features
    return InjectionEvent(
        event_uid=event_uid,
        injection_id=injection_id,
        thread_id=THREAD_ID,
        agent_id="general",
        machine_id=MACHINE_ID,
        principal_id=PRINCIPAL_ID,
        project_key=None,
        agent_kind="general",
        prompt_text="disposable M2Z4 learner proof",
        scorer_version=INCUMBENT_VERSION,
        memory_id=memory_id,
        memory_kind="fact",
        features={
            "sem": sem,
            "kw": kw,
            "time": time,
            "proj": proj,
            "freq": freq,
            "hist": hist,
            "_memory": {"label": label, "body": body, "pin": False},
            "_prepare": {"model_context_tokens": 8192},
        },
        score=score,
        rank=rank,
        shown_as=shown_as,
        actor_class="human",
        outcome=outcome,
        ts=ts,
    )


def _graded_work() -> tuple[InjectionEvent, ...]:
    """Two graded gates guarantee a replay winner; the third gate is audition-only."""

    base = datetime(2026, 8, 9, 18, 0, tzinfo=UTC)
    positive = UUID("00000000-0000-4000-8000-000000000405")
    negative = UUID("00000000-0000-4000-8000-000000000406")
    candidate = UUID("00000000-0000-4000-8000-000000000407")
    rows: list[InjectionEvent] = []
    for gate, hour in ((1001, 0), (1002, 1)):
        injection_id = UUID(f"00000000-0000-4000-8000-{gate:012d}")
        at = base + timedelta(hours=hour)
        rows.extend(
            (
                _event(
                    event_uid=f"01KZ4Z000000000000000{gate:04d}P",
                    injection_id=injection_id,
                    memory_id=positive,
                    label="Recall the owner boundary",
                    body="Keep the owner boundary explicit.",
                    features=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                    score=0.42,
                    rank=2,
                    shown_as="near_miss",
                    outcome="added_back",
                    ts=at,
                ),
                _event(
                    event_uid=f"01KZ4Z000000000000000{gate:04d}N",
                    injection_id=injection_id,
                    memory_id=negative,
                    label="Ignore an irrelevant branch",
                    body="This branch was irrelevant to the owner request.",
                    features=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                    score=0.0,
                    rank=1,
                    shown_as="injected",
                    outcome="removed:not_relevant",
                    ts=at,
                ),
            )
        )
    rows.append(
        _event(
            event_uid="01KZ4Z00000000000000001003",
            injection_id=CURRENT_INJECTION_ID,
            memory_id=candidate,
            label="No silent inference",
            body="Do not silently resolve an ambiguous owner choice.",
            features=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            score=0.42,
            rank=1,
            shown_as="near_miss",
            outcome=None,
            ts=base + timedelta(hours=2),
        )
    )
    return tuple(rows)


def create_integration_app() -> FastAPI:
    """Start one disposable Postgres/Spine/Harness proof process."""

    container_type = _postgres_container_type()
    postgres = container_type(
        "pgvector/pgvector:pg16",
        username="spine",
        password="spine",
        dbname="spine",
    )
    try:
        postgres.start()
        database_url = _asyncpg_url(postgres.get_connection_url())
        engine = create_async_engine(database_url)
    except BaseException:
        postgres.stop()
        raise

    sessions = make_session_factory(engine)
    spine_settings = SpineSettings(
        database_url=database_url,
        token=TOKEN,
        learner_min_dispositions=4,
        learner_holdout_fraction=0.49,
        learner_pair_margin=0.8,
        learner_bias_l2=1.0,
        learner_win_margin=1.0,
        retrain_signal_stride=2,
    )
    spine_app = create_spine_app(
        spine_settings,
        session_factory=sessions,
        embedding_provider=_UnusedEmbeddingProvider(),
    )
    spine_client = SpineClient(
        "http://disposable-spine.invalid",
        TOKEN,
        transport=httpx.ASGITransport(app=spine_app),
    )
    state: dict[str, Any] = {
        "fixture_graded_work_inserted": False,
        "worker_wake_requests": [],
        "worker_completions": [],
        "console_reads": 0,
        "canonical_console": None,
        "simulations": [],
        "auditions": [],
        "activation_attempts": [],
    }
    insert_lock = asyncio.Lock()

    learner_service = spine_app.state.learner_service
    actual_retrain_if_due = learner_service.retrain_if_due

    async def observed_retrain_if_due() -> SpineRetrainResponse | None:
        started_at = datetime.now(UTC)
        try:
            result = await actual_retrain_if_due()
        except BaseException as error:
            state["worker_completions"].append(
                {
                    "started_at": started_at.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "status": "error",
                    "error_type": type(error).__name__,
                }
            )
            raise
        state["worker_completions"].append(
            {
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "status": "not_due" if result is None else result.status,
                "proposal_version": None if result is None else result.proposal_version,
                "eligible_dispositions": (None if result is None else result.eligible_dispositions),
            }
        )
        return result

    # Verification instrumentation only: the worker still owns and invokes the
    # real service method; this wrapper records its completed return value.
    learner_service.retrain_if_due = observed_retrain_if_due

    async def read_console(thread_id: str | None) -> ScorerConsoleSnapshot:
        query = ScorerConsoleQuery(
            principal_id=PRINCIPAL_ID,
            thread_id=None if thread_id is None else UUID(thread_id),
            as_of="now",
        )
        snapshot = await spine_client.scorer_console(query)
        state["console_reads"] += 1
        state["canonical_console"] = snapshot.model_dump(mode="json")
        return snapshot

    async def simulate(body: RackScorerSimulationRequest) -> ScorerSimulationResponse:
        state["simulations"].append(body.model_dump(mode="json"))
        return await spine_client.simulate_scorer(
            ScorerSimulationRequest(
                principal_id=PRINCIPAL_ID,
                **body.model_dump(),
            )
        )

    async def audition(body: RackScorerAuditionRequest) -> ScorerAuditionResponse:
        response = await spine_client.audition_scorer(
            ScorerAuditionRequest(
                principal_id=PRINCIPAL_ID,
                **body.model_dump(),
            )
        )
        state["auditions"].append(
            {
                "request": body.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            }
        )
        return response

    async def refuse_activation(
        version: str,
        body: RackScorerActivateRequest,
    ) -> ScorerConfigurationView:
        state["activation_attempts"].append({"version": version, **body.model_dump(mode="json")})
        raise SpineClientError("the disposable M2Z4 proof never activates a proposal")

    def scenario_routes(app: FastAPI) -> None:
        install_fixture_isolation(app, FIXTURE)

        @app.post("/__scenario__/graded-work")
        async def insert_fixture_graded_work() -> dict[str, object]:
            """Test-only work driver: insert into the disposable DB, then notify the worker."""

            async with insert_lock:
                if state["fixture_graded_work_inserted"]:
                    raise HTTPException(status_code=409, detail="graded work already inserted")
                rows = _graded_work()
                async with sessions() as session, session.begin():
                    session.add_all(rows)
                state["fixture_graded_work_inserted"] = True
                notification = {
                    "requested_at": datetime.now(UTC).isoformat(),
                    "inserted_events": len(rows),
                    "eligible_dispositions": 4,
                    "test_only": True,
                    "database": "fresh disposable pgvector Testcontainer",
                }
                state["worker_wake_requests"].append(notification)
                spine_app.state.learner_worker.notify()
                return notification

        @app.get("/__scenario__/trace")
        async def trace() -> dict[str, object]:
            return await _trace(sessions, state)

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    harness_app = create_app(
        web_dist,
        scorer_console_reader=read_console,
        scorer_simulator=simulate,
        scorer_auditioner=audition,
        scorer_proposal_activator=refuse_activation,
        before_static_mount=scenario_routes,
    )
    harness_lifespan = harness_app.router.lifespan_context

    @asynccontextmanager
    async def integrated_lifespan(app: FastAPI):
        try:
            # Uvicorn evaluates ASGI factories inside its event loop; Alembic's
            # synchronous entry point owns a separate loop and therefore runs
            # in a worker thread before Spine's worker can touch the database.
            await asyncio.to_thread(upgrade_head, database_url)
            async with spine_app.router.lifespan_context(spine_app):
                async with harness_lifespan(app):
                    yield
        finally:
            await spine_client.aclose()
            await engine.dispose()
            await asyncio.to_thread(postgres.stop)

    harness_app.router.lifespan_context = integrated_lifespan
    return harness_app


async def _trace(
    sessions: async_sessionmaker[AsyncSession],
    state: dict[str, Any],
) -> dict[str, object]:
    async with sessions() as session:
        runs = (
            (await session.execute(select(LearnerRun).order_by(LearnerRun.ts, LearnerRun.run_uid)))
            .scalars()
            .all()
        )
        configs = (
            (
                await session.execute(
                    select(ScorerConfig).order_by(
                        ScorerConfig.created_at,
                        ScorerConfig.version,
                    )
                )
            )
            .scalars()
            .all()
        )
        activation_rows = await session.scalar(select(func.count()).select_from(ScorerActivation))
    active = [row.version for row in configs if row.active]
    proposals = [
        {
            "version": row.version,
            "active": row.active,
            "learner_status": (
                row.params.get("_learner", {}).get("status")
                if isinstance(row.params.get("_learner"), dict)
                else None
            ),
        }
        for row in configs
        if isinstance(row.params.get("_learner"), dict)
    ]
    return {
        "fixture": FIXTURE,
        "evidence_scope": (
            "one disposable integration proof; fixture-graded events exist only in this fresh "
            "test database and never touch an owner Palace"
        ),
        "schema_revision": packaged_head(),
        "worker": {
            "implementation": "spine.learner.worker.LearnerWorker",
            "wake_requests": list(state["worker_wake_requests"]),
            "completions": list(state["worker_completions"]),
        },
        "database": {
            "learner_runs": [
                {
                    "run_uid": row.run_uid,
                    "trigger": row.trigger,
                    "result": row.result,
                    "incumbent_version": row.incumbent_version,
                    "proposal_version": row.proposal_version,
                    "eligible_dispositions": row.eligible_dispositions,
                    "ts": row.ts.isoformat(),
                }
                for row in runs
            ],
            "active_versions": active,
            "learner_proposals": proposals,
            "activation_rows": activation_rows,
        },
        "harness": {
            "console_reads": state["console_reads"],
            "canonical_console": state["canonical_console"],
            "simulations": list(state["simulations"]),
            "auditions": list(state["auditions"]),
            "activation_attempts": list(state["activation_attempts"]),
        },
    }


__all__ = ["create_integration_app"]
