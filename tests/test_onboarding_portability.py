"""M3OB front-door regressions discovered in the disposable public walk."""

import io
import json
from dataclasses import replace

from harness import onboarding


def test_offline_init_never_discovers_or_downloads_and_uses_only_local_models(
    tmp_path, monkeypatch
):
    """P4.1 / FL-164 must work with no external network or provider key."""

    def unexpected(*args, **kwargs):
        raise AssertionError("offline initialization attempted discovery or download")

    monkeypatch.setattr(onboarding, "_discover_cloud_palace", unexpected)
    monkeypatch.setattr(onboarding, "_ensure_tool_runtimes", unexpected)
    onboarding.init_nocturne(
        home=tmp_path,
        offline=True,
        verification=True,
        environ={},
        prompt=unexpected,
        stdout=io.StringIO(),
    )
    config = onboarding.load_config(home=tmp_path)
    assert config.palace_mode == "local"
    assert config.principal_id.startswith("nocturne-verification-")
    assert config.openrouter_api_key == ""
    environment = config.process_environment({"OPENROUTER_API_KEY": "must-not-be-used"})
    assert environment["OPENROUTER_API_KEY"] == ""
    assert environment["CHAT_MODEL"] == "openai:qwen3:1.7b"
    assert environment["SPINE_EMBED_BASE_URL"] == "http://127.0.0.1:11434/v1"


def test_update_selects_latest_complete_pair_and_repairs_a_partial_install(tmp_path, monkeypatch):
    """P4.1 / FL-167 updates the two distributions together without downgrades."""
    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="fixture",
        spine_token="fixture",
        database_password="fixture",
        machine_id="fixture",
    )
    monkeypatch.setattr(onboarding, "load_config", lambda: config)
    monkeypatch.setattr(
        onboarding,
        "distribution_version",
        lambda name: "0.1.32" if name == "nocturne-memory" else "0.1.31",
    )

    class Response:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            releases = {"0.1.32": [{"yanked": False}], "0.1.34": [{"yanked": True}]}
            if "nocturne-memory" in self.url:
                releases["0.1.33"] = [{"yanked": False}]
            return json.dumps({"releases": releases}).encode()

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", lambda url, **kwargs: Response(url))
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: "/bin/uv")
    commands = []
    monkeypatch.setattr(onboarding, "_run", commands.append)
    assert onboarding.update_nocturne(prompt=lambda _: "yes", stdout=io.StringIO())
    assert commands[0][-2:] == ["nocturne-memory==0.1.32", "nocturne-harness==0.1.32"]
    monkeypatch.setattr(onboarding, "load_config", lambda: replace(config, local_model="local"))
    assert onboarding.update_nocturne(prompt=lambda _: "yes", stdout=io.StringIO()) is False
    assert len(commands) == 1
