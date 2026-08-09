"""Live-contract Spine factory with deterministic, local-only embeddings."""

from __future__ import annotations

import math
from collections.abc import Sequence

from spine.embeddings import EmbeddingInputError
from spine.main import create_app as create_spine_app

DIMENSIONS = 1536


def _basis(axis: int) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[axis] = 1.0
    return vector


def _with_cosine(score: float, *, axis: int, other_axis: int) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[axis] = score
    vector[other_axis] = math.sqrt(1.0 - score**2)
    return vector


VECTORS = {
    "A contract test must reject an exact duplicate memory body.": _basis(0),
    "The Palace stores durable memories for the owner and retrieves them when relevant.": (
        _basis(2)
    ),
    "The Palace keeps persistent memories for its owner and finds the useful records later.": (
        _with_cosine(0.85, axis=2, other_axis=3)
    ),
    "H2 CAS original": _basis(4),
    "H2 CAS patched": _basis(5),
}


class ContractEmbeddingProvider:
    """Serve only the vectors explicitly used by the live contract scenarios."""

    model = "h2-contract-embedding-1536"
    dimensions = DIMENSIONS

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            return [list(VECTORS[text]) for text in texts]
        except KeyError as exc:
            raise EmbeddingInputError(
                f"live-contract embedding fixture has no vector for {exc.args[0]!r}"
            ) from exc


def create_app():
    """Compose the production Spine app with its enacted provider-injection seam."""

    return create_spine_app(embedding_provider=ContractEmbeddingProvider())
