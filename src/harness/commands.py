"""Framework-free parsing for daemon-owned direct commands."""


def remember_command_text(text: str) -> str | None:
    """Return the exact `/remember` argument, or None for ordinary chat."""

    prefix = "/remember"
    if text == prefix:
        return ""
    if text.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)].isspace():
        return text[len(prefix) :].strip()
    return None


def model_command_text(text: str) -> str | None:
    """Return the exact `/model` argument, or None for ordinary chat."""

    prefix = "/model"
    if text == prefix:
        return ""
    if text.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)].isspace():
        return text[len(prefix) :].strip()
    return None
