"""Deterministic, visibly bannered M2J parameter-registry fixture."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI

from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.model_policy import ThreadModelResolution
from harness.onboarding import nocturne_home
from harness.transcript import TranscriptJournal
from verification.m2h.scenario_app import FixtureSpine


class FixtureResolver:
    def __init__(self) -> None:
        self.named: list[dict[str, str]] = []

    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        return ThreadModelResolution(
            model="openrouter:fixture/base",
            context_tokens=32_000,
            policy="pinned:openrouter:fixture/base",
        )

    async def resolve_named(self, thread_id: str, model: str) -> ThreadModelResolution:
        self.named.append({"thread_id": thread_id, "model": model})
        if model not in {"openrouter:fixture/base", "openrouter:fixture/next"}:
            from harness.model_policy import NamedModelResolutionError

            raise NamedModelResolutionError(f"unknown OpenRouter model: {model}")
        return ThreadModelResolution(
            model=model,
            context_tokens=64_000 if model.endswith("/next") else 32_000,
            policy="human_control",
        )


def create_scenario_app() -> FastAPI:
    resolver = FixtureResolver()
    journal = TranscriptJournal(nocturne_home() / "transcripts")
    settings = HarnessSettings(
        principal_id="m2j-verification",
        machine_id="m2j-verification-machine",
        agent_id="m2j-verification-agent",
        chat_model="openrouter:fixture/base",
        model_context_tokens=32_000,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        spine=FixtureSpine(),  # type: ignore[arg-type]
        transcript_journal=journal,
        model_resolver_override=resolver,
    )
    app = FastAPI(title="M2J deterministic verification")

    @app.get("/__scenario__/identity")
    async def identity() -> dict[str, object]:
        return {"fixture": "M2J REGRESSION", "deterministic": True}

    @app.get("/__scenario__/trace")
    async def trace() -> dict[str, object]:
        events: list[object] = []
        for path in sorted(Path(journal.root).glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("record_type") != "event":
                    continue
                event = record.get("event", {})
                if event.get("type") in {
                    "parameter.change",
                    "parameter.refused",
                    "model.change",
                }:
                    events.append(event)
        return {"named_resolutions": resolver.named, "events": events}

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
