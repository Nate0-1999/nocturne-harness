"""M8MF disposable local Palace, following report 317's installed-app walk."""

import os
import sys
from pathlib import Path

from harness.onboarding import load_config

WALK = Path("/Users/nateoswalt/relay/m8mf/walk")
HOME = WALK / "home"
MINI = "openrouter:openai/gpt-4.1-mini"
os.environ["NOCTURNE_HOME"] = str(HOME)
config = load_config(home=HOME)
assert config.palace_mode == "local" and config.principal_id.startswith("nocturne-verification-")
env = {**os.environ, **config.process_environment()}
env.update(
    PATH=str(WALK.parent / "scratch/no-rg-bin"),
    SPINE_URL="http://127.0.0.1:8186",
    CHAT_MODEL=MINI,
    SPINE_CHAT_MODEL="openai:gpt-4.1-mini",
    SPINE_OWNER_PRINCIPAL_ID=config.principal_id,
)
for role in ("CHAT", "SUBAGENT", "JUDGE"):
    env[f"MODEL_POLICY_{role}"] = f"pinned:{MINI}"
os.environ.update(env)
if sys.argv[1] == "db":
    import subprocess

    from spine.db.migrate import upgrade_head

    from harness.lifecycle import _compose_command

    with _compose_command(config) as compose:
        subprocess.run([*compose, "up", "--detach", "--wait", "postgres"], check=True)
    upgrade_head(config.database_url)
else:
    import uvicorn

    service = "spine.main:create_app" if sys.argv[1] == "spine" else "harness.packaged:create_app"
    uvicorn.run(
        service,
        factory=True,
        host="127.0.0.1",
        port=8186 if sys.argv[1] == "spine" else 8886,
    )
