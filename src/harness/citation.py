"""Deterministic ADR-005 citation detection for selected memory bodies."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

_MAX_NGRAM = 8
_MIN_BODY_TOKENS = 4


def cited_memory_ids(
    assistant_text: str,
    memory_bodies: Mapping[UUID, str],
) -> tuple[UUID, ...]:
    """Return memories whose body n-gram occurs in final assistant text. [A-036]"""

    output_tokens = _tokens(assistant_text)
    cited: list[UUID] = []
    for memory_id in sorted(memory_bodies, key=lambda value: value.int):
        body_tokens = _tokens(memory_bodies[memory_id])
        if len(body_tokens) < _MIN_BODY_TOKENS:
            continue
        size = min(_MAX_NGRAM, len(body_tokens))
        body_ngrams = _ngrams(body_tokens, size)
        if body_ngrams & _ngrams(output_tokens, size):
            cited.append(memory_id)
    return tuple(cited)


def _tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []
    for character in value.lower():
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


def _ngrams(tokens: tuple[str, ...], size: int) -> set[tuple[str, ...]]:
    if size <= 0 or len(tokens) < size:
        return set()
    return {tokens[index : index + size] for index in range(len(tokens) - size + 1)}


__all__ = ["cited_memory_ids"]
