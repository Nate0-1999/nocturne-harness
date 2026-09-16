"""PLAN M3SJ / ADR-024: workflows retain global walls and add their own ceiling."""

import asyncio
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from test_spend_walls import Emitter, Gateway

from harness.spend_walls import SpendLimits, SpendWallModel, SpendWalls, workflow_budget


@pytest.mark.asyncio
@pytest.mark.parametrize("global_wall,recipe_wall", [("0.01", "1"), ("1", "0.01")])
async def test_stricter_wall_prevents_second_purchase(tmp_path, global_wall, recipe_wall):
    """ADR-024 / M3SJ: neither the recipe nor the app's budget bypasses the smaller wall."""
    gateway, emitter, calls = Gateway(), Emitter(), []
    walls = SpendWalls(tmp_path / "walls.json", gateway, gateway.read)
    await walls.configure(SpendLimits(run_usd=Decimal(global_wall)))

    def respond(messages, info):
        calls.append(True)
        return ModelResponse(parts=[TextPart("done")], provider_details={"cost": "0.02"})

    model = SpendWallModel(FunctionModel(respond))

    async def work():
        with workflow_budget(Decimal(recipe_wall)), walls.bind("job-run", emitter):
            await model.request([], None, ModelRequestParameters())
            await model.request([], None, ModelRequestParameters())

    task = asyncio.create_task(work())
    await asyncio.wait_for(emitter.paused.wait(), 1)
    assert len(calls) == 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
