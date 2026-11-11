"""M7LF disposable local Palace and Linux host; no credential values enter receipts."""

import json
import os
import secrets
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx

from harness.lifecycle import _compose_command
from harness.onboarding import _default_postgres_volume, _write_config, init_nocturne, load_config

ROOT = Path("/Users/nateoswalt/relay/m7lf")
HOME = Path(os.environ.get("NOCTURNE_HOME", ROOT / "home-local"))
MINI = "pinned:openrouter:openai/gpt-4.1-mini"


def init():
    values = {}
    source = Path("/Users/nateoswalt/Developer/N8_Harness/harness/.env")
    for line in source.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    init_nocturne(
        remote=values["SPINE_URL"],
        verification=True,
        home=HOME,
        environ={
            "OPENROUTER_API_KEY": values["OPENROUTER_API_KEY"],
            "SPINE_TOKEN": values["SPINE_TOKEN"],
        },
        prompt=lambda _: "n",
    )
    config = replace(
        load_config(home=HOME),
        palace_mode="local",
        spine_url="http://127.0.0.1:8059",
        spine_token=secrets.token_urlsafe(32),
        postgres_port=55498,
        daemon_port=8899,
        palace_name="local-m7lf",
    )
    _write_config(config)
    (HOME / "model-policies.json").write_text(
        json.dumps(
            dict.fromkeys(
                ("chat", "subagent", "judge"),
                MINI,
            )
        )
    )
    with _compose_command(config) as compose:
        subprocess.run([*compose, "up", "--detach", "--wait", "postgres"], check=True)
    from spine.db.migrate import upgrade_head

    upgrade_head(config.database_url)
    print("Disposable local Palace ready; verification identity only.")


def linux():
    path = HOME / "env"
    path.write_text(
        "\n".join(
            line
            for line in path.read_text().splitlines()
            if "NOCTURNE_POSTGRES_VOLUME=" not in line
        )
        + f'\nNOCTURNE_POSTGRES_VOLUME="{_default_postgres_volume(HOME)}"\n'
    )
    config = replace(
        load_config(home=HOME),
        machine_id=f"nocturne-{uuid.uuid4()}",
        daemon_port=8898,
        spine_url="http://host.docker.internal:8059",
    )
    _write_config(config)
    print("Linux verification home configured.")


def serve(service, port):
    config = load_config(home=HOME)
    environment = {
        **os.environ,
        **config.process_environment(),
        "NOCTURNE_HOME": str(HOME),
        "SPINE_OWNER_PRINCIPAL_ID": config.principal_id,
        "CHAT_MODEL": "openrouter:openai/gpt-4.1-mini",
        "MODEL_POLICY_CHAT": MINI,
        "MODEL_POLICY_SUBAGENT": MINI,
        "MODEL_POLICY_JUDGE": MINI,
        "SPINE_URL": "http://host.docker.internal:8059"
        if sys.platform == "linux"
        else "http://127.0.0.1:8059",
    }
    app = "spine.main:create_app" if service == "spine" else "harness.packaged:create_app"
    os.execvpe(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            app,
            "--factory",
            "--host",
            "0.0.0.0" if sys.platform == "linux" else "127.0.0.1",
            "--port",
            port,
        ],
        environment,
    )


def usage(label):
    config = load_config(home=HOME)
    response = httpx.get(
        "https://openrouter.ai/api/v1/key",
        timeout=20,
        headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
    )
    response.raise_for_status()
    data = response.json()["data"]
    path = ROOT / "checks/key-usage.json"
    records = json.loads(path.read_text()) if path.exists() else []
    record = {
        "at": datetime.now(UTC).isoformat(),
        "label": label,
        "usage": data["usage"],
        "limit": data.get("limit"),
        "limit_remaining": data.get("limit_remaining"),
    }
    records.append(record)
    path.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(record))
    if records[-1]["usage"] - records[0]["usage"] >= 3:
        raise SystemExit("STOP: shared-key packet spend cap reached")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "init":
        init()
    elif mode == "linux":
        linux()
    elif mode == "usage":
        usage(sys.argv[2])
    elif mode == "serve":
        serve(*sys.argv[2:])
