import json
from pathlib import Path

import pytest

from harness.t3_client import RunTransitions, T3Error
from harness.t3_server import T3Server


def test_recorded_interrupt_closes_once_even_after_replay():
    """A-095: a native interrupt replay must close the Nocturne run once."""
    frames = json.loads((Path(__file__).parent / "fixtures/t3/terminal-replay.json").read_text())
    reducer = RunTransitions()
    transitions = [reducer.terminal(frame["event"]) for frame in frames + frames]
    assert [value for value in transitions if value] == ["interrupted"]


@pytest.mark.asyncio
async def test_optional_server_starts_only_on_request_and_names_missing_install(tmp_path):
    """F256: ordinary conversations work without installing the optional model loop."""
    server = T3Server(tmp_path)
    assert not server.root.exists()
    await server.close()
    with pytest.raises(T3Error, match="nocturne t3 install"):
        await server.client()
    assert not server.root.exists()


def test_inventory_keeps_private_auth_and_untrusted_labels_out_of_source_rows():
    """A-095: status can include the native account email; Nocturne exposes only public fields."""
    from harness.t3_sources import project_sources

    account_email = "person" + "@" + "example.test"
    provider = {
        "instanceId": "codex",
        "installed": True,
        "status": "ready",
        "version": "1.2.3",
        "auth": {
            "status": "authenticated",
            "type": "chatgpt",
            "workspaceId": "account-one",
            "email": account_email,
            "label": account_email,
        },
        "models": [{"slug": "gpt-model", "name": account_email}, {"slug": account_email}],
        "usageLimits": {
            "windows": [
                {"modelIds": ["gpt-model"], "usedPercent": 100, "resetsAt": "2026-11-22T23:00:00Z"}
            ]
        },
        "message": account_email,
    }
    rows = project_sources([provider])
    assert account_email not in json.dumps(rows) and "account-one" not in json.dumps(rows)
    assert rows[0]["availability"] == "available"
    assert rows[0]["models"][0]["availability"] == "limited"
    assert rows[0]["models"][0]["limited_until"] == "2026-11-22T23:00:00+00:00"
    provider["auth"]["type"] = "apiKey"
    assert project_sources([provider])[0]["availability"] == "unknown"
