from uuid import UUID

from harness.citation import cited_memory_ids


def test_citation_uses_deterministic_unicode_alphanumeric_ngrams() -> None:
    """ADR-005 reuse is punctuation-insensitive and bounded by exact body text. [A-036]"""

    cited = UUID(int=2)
    missed = UUID(int=1)
    bodies = {
        cited: "Café owners preserve eight bright copper garden lanterns nightly.",
        missed: "Different owners preserve seven dim silver hallway sconces weekly.",
    }

    assert cited_memory_ids(
        "The CAFÉ owners preserve eight bright copper garden lanterns nightly!",
        bodies,
    ) == (cited,)


def test_citation_requires_full_short_body_and_ignores_tiny_memories() -> None:
    """A-036 keeps short exact facts usable but rejects bodies below four tokens."""

    exact = UUID(int=3)
    tiny = UUID(int=4)
    bodies = {exact: "favorite color is blue", tiny: "likes blue tea"}

    assert cited_memory_ids("Their favorite color is blue, and they like tea.", bodies) == (exact,)
