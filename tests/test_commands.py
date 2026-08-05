import pytest

from harness.commands import model_command_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/model", ""),
        ("/model   ", ""),
        ("/model\topenrouter:vendor/model ", "openrouter:vendor/model"),
        ("/models openrouter:vendor/model", None),
        ("prefix /model openrouter:vendor/model", None),
        (" /model openrouter:vendor/model", None),
    ],
)
def test_model_command_parses_only_the_exact_direct_command(
    text: str,
    expected: str | None,
) -> None:
    """A-021 is defended by verifying that model command parses only the exact direct command;
    this prevents drift in the explicit model command grammar.
    """
    assert model_command_text(text) == expected
