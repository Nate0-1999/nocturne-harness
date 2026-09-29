"""Seed walk memories into the TEST palace (test-m3exf) under the verification principal."""
import asyncio
from harness.onboarding import load_config
from harness.spine_client import SpineClient, CreateMemoryRequest, MemoryKind

FACTS = [
    ("Web UI test location", "Web UI tests live in harness/web/tests and run with npm test.", ["web", "tests", "npm"]),
    ("Python test command", "Python tests run with .venv/bin/python -m pytest -q from the harness folder.", ["python", "pytest"]),
    ("Spine test containers", "Spine tests need TESTCONTAINERS_RYUK_DISABLED=true and the colima docker socket override.", ["spine", "docker"]),
    ("Commit style", "Commit names are problem to solution oriented and narrow in scope.", ["git", "commits"]),
    ("Chamfered buttons", "Buttons use chamfered corners cut with clip-path, never rounded corners.", ["ui", "buttons"]),
    ("Theme tokens", "Colors come only from the theme tokens in web/src/themes; never invent a color.", ["ui", "themes"]),
    ("Release order", "Release the Memory package first, then the Harness package, at the next unused version.", ["release"]),
    ("Test palace rule", "Anything a verification walk creates in the cloud goes on a test palace dropped afterwards.", ["palace", "verification"]),
    ("Sheet view clicks", "The Stage is CSS-scaled; walk clicks inside module frames in the Sheet view.", ["walk", "sheet"]),
    ("Scratch home", "Every hand-launched daemon runs under a scratch NOCTURNE_HOME, never the owner's home.", ["home", "walk"]),
    ("Model default", "OpenRouter is the default broker for chat and embeddings.", ["openrouter", "models"]),
    ("Icons on buttons", "Familiar actions carry an icon from the one adopted icon set, drawn in the theme ink.", ["ui", "icons"]),
]

async def main():
    config = load_config()
    assert config.palace_name == "test-m3exf", config.palace_name
    client = SpineClient(config.spine_url, config.spine_token, principal_id=config.principal_id)
    for label, body, keywords in FACTS:
        response = await client.create_memory(CreateMemoryRequest(
            principal_id=config.principal_id, label=label, body=body, kind=MemoryKind.FACT,
            keywords=keywords, editor="m3exf-walk-seed", machine_id=config.machine_id))
        print(type(response).__name__, label)

asyncio.run(main())
