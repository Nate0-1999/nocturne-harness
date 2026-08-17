"""Typed host-side results for ADR-023's public rack query surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from harness.context_window import ContextWindowSnapshot
from harness.parameter_registry import ParameterSnapshot
from harness.recipe_graph import RecipeGraphSnapshot
from harness.spine_client import MemoryGraphSnapshot, ScorerConsoleSnapshot, VitalsSnapshot


class RackQueryResult(BaseModel):
    """One live query value or a truthful unsupported historical request."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["live", "historical_unavailable"]
    as_of: str | None
    data: (
        VitalsSnapshot
        | ParameterSnapshot
        | MemoryGraphSnapshot
        | ScorerConsoleSnapshot
        | ContextWindowSnapshot
        | RecipeGraphSnapshot
        | None
    )

    @model_validator(mode="after")
    def require_status_shape(self) -> RackQueryResult:
        if self.status == "live":
            if self.as_of is not None or self.data is None:
                raise ValueError("a live rack query requires data and a null as_of")
            return self
        if self.as_of is None or self.data is not None:
            raise ValueError("a historical-unavailable rack query requires its as_of and null data")
        return self


__all__ = ["RackQueryResult"]
