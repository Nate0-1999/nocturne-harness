"""M3WF local-only learning fixture; real gates, explicit fixture eligibility."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace

from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from verification.fixture_isolation import install_fixture_isolation

HOME = Path("/private/tmp/m3fx-step6-home")
SECOND_HOME = Path("/private/tmp/m3fx-step6-second-home")
PRINCIPAL = "nocturne-verification-fixture-m3wf"
MACHINE = "nocturne-fixture-m3wf-machine-a"
MODEL = "openai-chat:mlx-community/Qwen3-1.7B-4bit"


def fixture_config():
    assert os.environ.get("NOCTURNE_HOME") in {str(HOME), str(SECOND_HOME)}
    # Dedicated disposable database; these public fixture credentials grant no
    # access to a real Palace. Never load the owner's or another fixture's config.
    return SimpleNamespace(
        database_url="postgresql+asyncpg://m3wf:m3wf-fixture@127.0.0.1:55436/m3wf",
        spine_token="m3wf-local-fixture-token",
    )


class LexicalFixtureEmbedding:
    """Deterministic bag-of-words fixture vectors, not learned semantic embeddings."""

    model = "m3wf-lexical-fixture"
    dimensions = 1536

    async def embed(self, texts):
        result = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for word in re.findall(r"[a-z]+", text.lower()):
                index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4]) % len(vector)
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            result.append([value / norm for value in vector])
        return result


def create_spine_app():
    from spine.config import Settings
    from spine.learner import evidence
    from spine.main import create_app

    config = fixture_config()
    # M3WF asks for authentic-class fixture signals. Only this local process
    # admits this visibly named fixture principal; stored identities stay honest.
    evidence.identity_is_excluded = lambda *, principal_id, machine_id: (
        principal_id != PRINCIPAL or machine_id != MACHINE
    )
    app = create_app(
        Settings(
            _env_file=None,
            database_url=config.database_url,
            token=config.spine_token,
            openai_api_key=None,
        ),
        embedding_provider=LexicalFixtureEmbedding(),
    )
    install_fixture_isolation(app, "M3WF REGRESSION")
    return app


def create_harness_app():
    return _harness_app(HOME, PRINCIPAL, MACHINE)


def create_second_harness_app():
    return _harness_app(SECOND_HOME, PRINCIPAL + "-second", "nocturne-fixture-m3wf-machine-b")


def _harness_app(home, principal, machine):
    assert os.environ.get("NOCTURNE_HOME") == str(home)
    config = fixture_config()
    workspace = home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:8900/v1"
    app = create_dev_app(
        web_dist=Path(__file__).resolve().parents[2] / "web/dist",
        settings=HarnessSettings(
            _env_file=None,
            nocturne_home=home,
            principal_id=principal,
            machine_id=machine,
            spine_url="http://127.0.0.1:8902",
            spine_token=config.spine_token,
            openai_api_key="fixture-local-no-secret",
            openrouter_api_key=None,
            anthropic_api_key=None,
            chat_model=MODEL,
            model_policy_chat="pinned:" + MODEL,
            model_context_tokens=4096,
            extraction_idle_hours=None,
        ),
    )
    install_fixture_isolation(app, "M3WF REGRESSION")
    return app
