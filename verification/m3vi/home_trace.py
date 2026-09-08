import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel
from test_daemon import GateSpine, frame, receive_until

from harness import onboarding
from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app


async def stream(_messages, _info):
    yield "unused"


with tempfile.TemporaryDirectory(prefix="m3vi-home-trace-") as root:
    root = Path(root)
    user = root / "fake-user"
    user.mkdir()
    home = root / "verification"
    os.environ.pop("NOCTURNE_HOME", None)
    with (
        patch.object(Path, "home", classmethod(lambda cls: user)),
        patch.object(onboarding, "ensure_browser_runtime", lambda home: home / "tools"),
        patch.object(onboarding, "browser_runtime_is_ready", lambda home: True),
    ):
        onboarding.init_nocturne(
            home=home,
            remote="https://palace.example.test",
            environ={"OPENROUTER_API_KEY": "test-key"},
            prompt=lambda message: "test-token" if "token" in message else "n",
            stdout=io.StringIO(),
        )
        settings = HarnessSettings(_env_file=home / "env")
        app = create_dev_app(
            root,
            settings=settings,
            spine=GateSpine(),
            agent=HarnessAgent(settings, model=FunctionModel(stream_function=stream)),
        )
        with TestClient(app) as client, client.websocket_connect("/ws") as socket:
            socket.send_json(frame("prompt.submit", {"prompt": "/model openrouter:test/model"}))
            receive_until(socket, "run.done")
        print(
            json.dumps(
                {
                    "env_persists_home": "NOCTURNE_HOME" in onboarding._parse_config(home / "env"),
                    "verification_journals": len(list((home / "transcripts").glob("*.jsonl"))),
                    "fallback_journals": len(
                        list((user / ".nocturne/transcripts").glob("*.jsonl"))
                    ),
                    "real_owner_home_accessed": False,
                }
            )
        )
