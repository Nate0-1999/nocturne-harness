"""Framework-free parsing for daemon-owned direct commands."""


def _command_argument(text: str, prefix: str) -> str | None:
    if text == prefix:
        return ""
    if text.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)].isspace():
        return text[len(prefix) :].strip()
    return None


def remember_command_text(text: str) -> str | None:
    """Return the exact `/remember` argument, or None for ordinary chat."""

    return _command_argument(text, "/remember")


def model_command_text(text: str) -> str | None:
    """Return the exact `/model` argument, or None for ordinary chat."""

    return _command_argument(text, "/model")


def move_command_text(text: str) -> str | None:
    """Return the exact `/move` argument, or None for ordinary chat. [Codex M3W5A-03]"""

    return _command_argument(text, "/move")


def browser_open_web_command(text: str) -> bool:
    """Match the sole owner command that grants this thread open-web access."""

    return text.strip() == "/browser allow-web"
